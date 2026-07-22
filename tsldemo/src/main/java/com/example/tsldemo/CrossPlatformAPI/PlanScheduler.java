package com.example.tsldemo.CrossPlatformAPI;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import com.example.tsldemo.Business; 
import com.example.tsldemo.SignInAPI.BusinessRepository; 

@Component
public class PlanScheduler {
    private static final String DAILY_CRON = "0 30 14 * * *";
    private static final ZoneId IRISH_ZONE = ZoneId.of("Europe/Dublin");

    @Autowired
    private PlanService planService;

    @Autowired
    private BusinessRepository businessRepository;
    
    @Autowired
    private JavaMailSender mailSender;

    @Scheduled(cron = DAILY_CRON, zone = "Europe/Dublin")
    public void runDailyPlanCheck() {
        String today = LocalDate.now(IRISH_ZONE).toString();
        System.out.println("[PlanScheduler] Checking due plan items for " + today);

        List<Business> businesses = businessRepository.findAll();

        for (Business business : businesses) {
            int businessId = business.getId();
            try {
                processDueItemsForBusiness(businessId, today);
            } catch (Exception e) {
                System.err.println("[PlanScheduler] Failed for business " + businessId + ": " + e.getMessage());
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void processDueItemsForBusiness(int businessId, String today) {
        Map<String, Object> due = planService.getDuePlans(today, businessId);
        List<Map<String, Object>> items = (List<Map<String, Object>>) due.getOrDefault("items", List.of());

        for (Map<String, Object> dueEntry : items) {
            String planId = (String) dueEntry.get("plan_id");
            Map<String, Object> item = (Map<String, Object>) dueEntry.get("item");
            String itemId = (String) item.get("item_id");
            boolean overdue = Boolean.TRUE.equals(dueEntry.get("overdue"));

            if (overdue) {
                System.out.println("[PlanScheduler] ALERT: item " + itemId + " in plan " + planId + " is overdue.");
            }

            try {
                Map<String, Object> result = planService.executePlanItem(planId, itemId, null);
                Map<String, Object> task = (Map<String, Object>) result.get("task");
                String taskId = task != null ? (String) task.get("task_id") : null;

                System.out.println("[PlanScheduler] Executed item " + itemId + " (plan " + planId
                        + ") -> task " + taskId + ". Notify business " + businessId + " to review it.");

                // TODO: Emailing at said time goes here
                String userEmail = businessRepository.findById(businessId).get().getEmail();
                
                sendEmail(
                		userEmail,
                	    "Plan item executed",
                	    "Today's scheduled post has started drafting. It will appear in your review queue shortly."
                );


            } catch (Exception e) {
                // 409 means "already started" (idempotency guard) — not a real error.
                if (e.getMessage() != null && e.getMessage().contains("409")) {
                    System.out.println("[PlanScheduler] Item " + itemId + " already executed — skipping.");
                } else {
                    System.err.println("[PlanScheduler] Failed to execute item " + itemId + ": " + e.getMessage());
                }
            }
        }
    }
    
    private void sendEmail(String to, String subject, String body) {
        SimpleMailMessage message = new SimpleMailMessage();

        message.setTo(to);
        message.setSubject(subject);
        message.setText(body);

        mailSender.send(message);

        System.out.println("[PlanScheduler] Email sent to " + to);
    }


}