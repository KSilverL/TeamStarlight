package com.example.tsldemo.CrossPlatformAPI;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import jakarta.annotation.PreDestroy;

/**
 * Drafts every slot in a campaign when the plan is confirmed.
 *
 * <p>Confirming used to activate the plan and nothing else — the copy for each slot was written
 * a day before that slot by {@link PlanScheduler}, so a three-week campaign trickled in over
 * three weeks. Approving a campaign now means its posts get written, so the whole schedule can
 * be reviewed as a body of work rather than a slot at a time.
 *
 * <p>The trade this accepts: copy is generated against the trends snapshot of the confirm day,
 * not of each slot's own publish day. That is the price of having the campaign in hand up front,
 * and it is why {@link PlanScheduler} still exists — see below.
 *
 * <p><b>The approval gate is untouched.</b> Each slot still stops at the human gate exactly as
 * before; this changes when the drafting happens, not whether a person signs it off.
 */
@Service
public class PlanCampaignDrafter {

    private static final Logger log = LoggerFactory.getLogger(PlanCampaignDrafter.class);

    @Autowired
    private PlanService planService;

    /**
     * How long to wait between starting one slot's draft and the next.
     *
     * <p>The LLM service starts each run in the background and returns immediately, so without
     * a pause here confirming a fifteen-slot campaign would fire fifteen concurrent workflow
     * runs within milliseconds — a burst of model calls that invites rate limiting and makes
     * every draft slower than doing them in turn. Staggering the starts spreads the same work
     * out; it costs nothing, because nobody can review a draft that hasn't been written yet.
     */
    @Value("${app.plans.draft-stagger-ms:5000}")
    private long staggerMs;

    /**
     * Single-threaded on purpose: one campaign drafts at a time, its slots staggered. Kept off
     * the shared {@code @Scheduled} pool so a long campaign can never starve the post sweeper,
     * which has publishing deadlines to hit.
     */
    private final ExecutorService worker = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "starlight-plan-drafter");
        thread.setDaemon(true);  // never hold up JVM shutdown for in-flight drafting
        return thread;
    });

    /**
     * Starts drafting every unstarted slot on a plan, and returns immediately.
     *
     * <p>Deliberately fire-and-forget. Drafting a campaign is minutes of model work, and the
     * caller is an HTTP request holding a user in front of a spinner — so confirm answers as
     * soon as the plan is active and the drafts arrive as they arrive.
     *
     * <p>Nothing here is durable: a restart mid-campaign leaves the rest of the slots
     * {@code planned}. That is survivable rather than sloppy, because {@link PlanScheduler}
     * still runs daily and picks up anything undrafted before its date arrives.
     */
    public void draftAll(String planId) {
        worker.submit(() -> {
            try {
                draft(planId);
            } catch (Exception e) {
                // The submitting request is long gone, so an escaping exception would vanish
                // into the executor's Future with nothing logged anywhere.
                log.error("[PlanCampaignDrafter] Drafting plan {} failed: {}", planId, e.toString(), e);
            }
        });
    }

    @SuppressWarnings("unchecked")
    private void draft(String planId) {
        Map<String, Object> plan = planService.getPlan(planId);
        List<Map<String, Object>> items =
                (List<Map<String, Object>>) plan.getOrDefault("items", List.of());

        List<Map<String, Object>> pending = items.stream()
                .filter(item -> "planned".equals(item.get("status")))
                .toList();

        log.info("[PlanCampaignDrafter] Plan {}: drafting {} slot(s)", planId, pending.size());

        int started = 0;
        for (Map<String, Object> item : pending) {
            String itemId = String.valueOf(item.get("item_id"));
            try {
                planService.executePlanItem(planId, itemId, null);
                started++;
                log.info("[PlanCampaignDrafter] Plan {} item {} drafting ({}/{})",
                        planId, itemId, started, pending.size());
            } catch (Exception e) {
                // A 409 means something already started this slot — the daily job, or a user
                // who pressed "Generate Draft Now". Either way it is being handled, and the
                // rest of the campaign must still go ahead.
                log.info("[PlanCampaignDrafter] Plan {} item {} not started: {}",
                        planId, itemId, e.getMessage());
            }

            if (!sleepBetweenItems()) {
                log.warn("[PlanCampaignDrafter] Plan {}: interrupted after {} slot(s); the daily "
                        + "job will pick up the rest", planId, started);
                return;
            }
        }

        log.info("[PlanCampaignDrafter] Plan {}: {} of {} slot(s) drafting", planId, started, pending.size());
    }

    /** @return false if the wait was interrupted (shutdown), meaning we should stop. */
    private boolean sleepBetweenItems() {
        if (staggerMs <= 0) {
            return true;
        }
        try {
            Thread.sleep(staggerMs);
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    @PreDestroy
    void shutdown() {
        worker.shutdownNow();
        try {
            worker.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
