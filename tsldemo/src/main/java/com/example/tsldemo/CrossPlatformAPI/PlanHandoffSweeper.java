package com.example.tsldemo.CrossPlatformAPI;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import com.example.tsldemo.Business;
import com.example.tsldemo.SignInAPI.BusinessRepository;

/**
 * Puts approved plan copy on the calendar, whoever approved it and wherever they did it.
 *
 * <p>The handoff was previously reachable only from the Approve button on the plans page: the
 * browser approved the draft and then, as a second request, asked the backend to schedule it.
 * That made scheduling a property of <em>where the user happened to be standing</em>. Approving
 * the same task from the chat view left the slot approved and unscheduled, and so did a browser
 * that closed, lost its connection, or simply had its second request fail — with nothing
 * anywhere to say the post was never queued.
 *
 * <p>So the database is the source of truth instead. A slot is outstanding when it has approved
 * copy and no live post for one of its schedulable platforms, and this sweep resolves anything
 * outstanding regardless of how it got that way. The browser's own call is now a fast path for
 * immediate feedback, not the mechanism.
 *
 * <p>The interval is minutes, not hours, for a reason the rest of the scheduling stack does not
 * have: the LLM service holds task outputs in memory, so approved copy is only recoverable
 * until that process restarts. A sweep that ran nightly would be a sweep that regularly found
 * the copy already gone.
 */
@Component
public class PlanHandoffSweeper {

    private static final Logger log = LoggerFactory.getLogger(PlanHandoffSweeper.class);

    @Autowired
    private PlanService planService;

    @Autowired
    private PlanHandoffService planHandoffService;

    @Autowired
    private BusinessRepository businessRepository;

    /** Same zone the rest of the scheduling stack pins to. */
    @Value("${app.timezone:Europe/Dublin}")
    private String timezone;

    @Scheduled(
            fixedDelayString = "${app.plans.handoff-sweep-interval-ms:120000}",
            initialDelayString = "${app.plans.handoff-sweep-initial-delay-ms:30000}")
    public void sweep() {
        try {
            LocalDate today = LocalDate.now(ZoneId.of(timezone));
            for (Business business : businessRepository.findAll()) {
                sweepBusiness(business.getId(), today);
            }
        } catch (Exception e) {
            // An escaping exception cancels this @Scheduled task for the life of the process,
            // and the symptom — approved posts silently never reaching the calendar — looks
            // nothing like its cause. Swallow it so the next tick still runs.
            log.error("[PlanHandoffSweeper] Sweep failed: {}", e.toString(), e);
        }
    }

    private void sweepBusiness(int businessId, LocalDate today) {
        List<Map<String, Object>> plans;
        try {
            plans = activePlans(businessId);
        } catch (Exception e) {
            log.error("[PlanHandoffSweeper] Could not list plans for business {}: {}",
                    businessId, e.toString());
            return;
        }

        for (Map<String, Object> summary : plans) {
            String planId = (String) summary.get("plan_id");
            if (planId == null) {
                continue;
            }
            try {
                sweepPlan(businessId, planId, today);
            } catch (Exception e) {
                // One unreachable or malformed plan must not cost the others their sweep.
                log.error("[PlanHandoffSweeper] Plan {} failed for business {}: {}",
                        planId, businessId, e.toString());
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void sweepPlan(int businessId, String planId, LocalDate today) {
        // Re-read the plan rather than trusting the list: only a single-plan read reconciles
        // item statuses against their workflow tasks, so the list's `awaiting_review` can be
        // an approval that already happened. Sweeping the list alone would never see it.
        Map<String, Object> plan = planService.getPlan(planId);
        List<Map<String, Object>> items =
                (List<Map<String, Object>>) plan.getOrDefault("items", List.of());

        for (Map<String, Object> item : items) {
            String itemId = String.valueOf(item.get("item_id"));

            if (isPast((String) item.get("planned_date"), today)) {
                continue;  // its publish moment is gone; scheduling would only be rejected
            }
            if (!planHandoffService.needsScheduling(businessId, planId, item)) {
                continue;
            }

            log.info("[PlanHandoffSweeper] Plan {} item {} is approved but not scheduled — "
                    + "scheduling it now", planId, itemId);
            try {
                Map<String, Object> result = planHandoffService.scheduleApprovedItem(
                        businessId, plan, itemId, List.of());
                log.info("[PlanHandoffSweeper] Plan {} item {}: {}", planId, itemId, result);
            } catch (Exception e) {
                // Expected and recoverable in the ordinary case — a slot mid-review reads as
                // approved for a moment before its last platform lands a verdict. Logged at
                // info because the next sweep retries it anyway.
                log.info("[PlanHandoffSweeper] Plan {} item {} not ready: {}",
                        planId, itemId, e.getMessage());
            }
        }
    }

    /**
     * A slot whose date has passed can no longer be scheduled — {@code ScheduledPostService}
     * rejects a past instant — so skipping it here is not a policy choice, it just avoids
     * asking the LLM service for copy we could not use. It also bounds the sweep: without it,
     * every never-scheduled slot in every finished campaign would be retried forever.
     */
    private static boolean isPast(String plannedDate, LocalDate today) {
        if (plannedDate == null) {
            return false;  // no date to judge by — let the handoff give the real reason
        }
        try {
            return LocalDate.parse(plannedDate).isBefore(today);
        } catch (Exception e) {
            return false;
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> activePlans(int businessId) {
        Map<String, Object> response = planService.listPlans(businessId, "active");
        return (List<Map<String, Object>>) response.getOrDefault("plans", List.of());
    }
}
