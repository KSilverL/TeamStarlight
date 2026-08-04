package com.example.tsldemo.CrossPlatformAPI;

import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import com.example.tsldemo.Business;
import com.example.tsldemo.SignInAPI.BusinessRepository;

/**
 * The backstop that drafts any plan slot still unwritten as its date approaches.
 *
 * <p>This used to be how every slot got written: a plan was confirmed, and each slot's copy was
 * drafted a day before its own date. {@link PlanCampaignDrafter} now writes the whole campaign
 * at confirm time, so in the ordinary case this job finds nothing to do.
 *
 * <p>It is still needed for the cases that miss that path, all of which end with a slot whose
 * date arrives with no copy against it:
 * <ul>
 *   <li>a restart part-way through drafting a campaign — the drafter holds no durable queue;</li>
 *   <li>slots added or un-skipped by a PATCH after the plan was confirmed;</li>
 *   <li>plans confirmed before campaign-time drafting existed;</li>
 *   <li>a slot whose first draft attempt failed.</li>
 * </ul>
 *
 * <p>It runs <em>ahead</em> of the slot rather than on the day of it. Generating a post at 18:00
 * for a slot planned that same morning is already too late — the window has passed, and a post
 * still has to clear the human gate before it can go anywhere. So the job asks for everything
 * due up to a horizon a configurable lead ahead of today.
 *
 * <p>Because the underlying query is "planned_date &lt;= horizon", widening the horizon also
 * keeps catching genuinely missed slots — those come back flagged overdue and are logged as
 * such.
 */
@Component
public class PlanScheduler {

    private static final Logger log = LoggerFactory.getLogger(PlanScheduler.class);

    @Autowired
    private PlanService planService;

    @Autowired
    private BusinessRepository businessRepository;

    @Autowired(required = false)
    private JavaMailSender mailSender;

    /** Same zone the rest of the scheduling stack pins to. */
    @Value("${app.timezone:Europe/Dublin}")
    private String timezone;

    /**
     * How many days ahead of a slot to draft its content.
     *
     * <p>One day is the useful minimum: the evening run drafts tomorrow, so even the earliest
     * morning slot (LinkedIn's 07:30) has a review window in front of it. Raising it gives more
     * slack for review at the cost of drafting against staler trends — the copy rides the trends
     * snapshot of the day it is generated, not the day it publishes.
     */
    @Value("${app.plans.generation-lead-days:1}")
    private long generationLeadDays;

    @Scheduled(
            cron = "${app.plans.generation-cron:0 0 18 * * *}",
            zone = "${app.timezone:Europe/Dublin}")
    public void runDailyPlanCheck() {
        ZoneId zone = ZoneId.of(timezone);
        LocalDate today = LocalDate.now(zone);
        String horizon = today.plusDays(generationLeadDays).toString();

        log.info("[PlanScheduler] Drafting plan items due on or before {} (today is {}, {} day(s) lead)",
                horizon, today, generationLeadDays);

        List<Business> businesses = businessRepository.findAll();

        for (Business business : businesses) {
            int businessId = business.getId();
            try {
                processDueItemsForBusiness(businessId, horizon, today.toString());
            } catch (Exception e) {
                log.error("[PlanScheduler] Failed for business {}: {}", businessId, e.getMessage());
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void processDueItemsForBusiness(int businessId, String horizon, String today) {
        Map<String, Object> due = planService.getDuePlans(horizon, businessId);
        List<Map<String, Object>> items =
                (List<Map<String, Object>>) due.getOrDefault("items", List.of());

        for (Map<String, Object> dueEntry : items) {
            String planId = (String) dueEntry.get("plan_id");
            Map<String, Object> item = (Map<String, Object>) dueEntry.get("item");
            String itemId = (String) item.get("item_id");
            String plannedDate = (String) item.get("planned_date");

            // `overdue` is computed against the horizon we asked for, so with a lead in play it
            // means "should have been drafted on an earlier run" — compare against the real
            // today to report the ones that actually missed their publish date.
            if (plannedDate != null && plannedDate.compareTo(today) < 0) {
                log.warn("[PlanScheduler] Item {} in plan {} was planned for {} — its date has "
                        + "already passed", itemId, planId, plannedDate);
            }

            try {
                Map<String, Object> result = planService.executePlanItem(planId, itemId, null);
                Map<String, Object> task = (Map<String, Object>) result.get("task");
                String taskId = task != null ? (String) task.get("task_id") : null;

                String slots = describeSlots(item);
                log.info("[PlanScheduler] Drafting item {} (plan {}) -> task {} for business {}; "
                        + "target slot(s): {}", itemId, planId, taskId, businessId, slots);

                notifyDrafting(businessId, plannedDate, slots);

            } catch (Exception e) {
                if (e.getMessage() != null && e.getMessage().contains("409")) {
                    log.info("[PlanScheduler] Item {} already executed — skipping", itemId);
                } else {
                    log.error("[PlanScheduler] Failed to execute item {}: {}", itemId, e.getMessage());
                }
            }
        }
    }

    /**
     * Renders the concrete publish moment each platform's copy is being drafted for.
     *
     * <p>The plan's {@code time_of_day} is free text ("morning", "18:00"), so this resolves it
     * the same way the scheduling handoff will — surfacing the real time now means a lead that
     * is too short shows up in the logs as a slot in the past, rather than as a scheduling
     * failure days later.
     */
    @SuppressWarnings("unchecked")
    private String describeSlots(Map<String, Object> item) {
        String timeOfDay = (String) item.getOrDefault("time_of_day", "");
        List<String> platforms = (List<String>) item.getOrDefault("platforms", List.of());
        String plannedDate = (String) item.get("planned_date");

        if (platforms.isEmpty()) {
            return "no platforms on this item";
        }

        List<String> described = new ArrayList<>();
        for (String platform : platforms) {
            LocalTime time = PostingWindowResolver.resolve(timeOfDay, platform);
            described.add(platform + " " + plannedDate + " " + time
                    + (PostingWindowResolver.isExplicit(timeOfDay) ? "" : " (default slot)"));
        }
        return String.join(", ", described);
    }

    /** Best-effort — a mail server that is down must not stop the rest of the batch drafting. */
    private void notifyDrafting(int businessId, String plannedDate, String slots) {
        if (mailSender == null) {
            return;
        }
        try {
            Business business = businessRepository.findById(businessId).orElse(null);
            if (business == null || business.getEmail() == null) {
                return;
            }
            sendEmail(
                    business.getEmail(),
                    "A planned post is being drafted",
                    "Your plan slot for " + plannedDate + " has started drafting and will appear "
                    + "in your review queue shortly.\n\nTarget: " + slots
                    + "\n\nReview it before then so it can go out on time.");
        } catch (Exception e) {
            log.error("[PlanScheduler] Could not email business {}: {}", businessId, e.getMessage());
        }
    }

    private void sendEmail(String to, String subject, String body) {
        SimpleMailMessage message = new SimpleMailMessage();

        message.setTo(to);
        message.setSubject(subject);
        message.setText(body);

        mailSender.send(message);

        log.info("[PlanScheduler] Email sent to {}", to);
    }
}
