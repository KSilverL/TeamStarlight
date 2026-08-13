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
 *
 * <p><b>One slot at a time.</b> Each slot's run is waited out before the next begins, so a
 * campaign is written in the order the user reads it: post one, then post two. Starting them
 * all at once finished no sooner in practice — the model calls queue behind each other anyway
 * — and it left the plan page with several slots half-written and nothing to say about any of
 * them. Sequential drafting means there is always exactly one live slot to point at, which is
 * the difference between a progress indicator and a spinner.
 */
@Service
public class PlanCampaignDrafter {

    private static final Logger log = LoggerFactory.getLogger(PlanCampaignDrafter.class);

    @Autowired
    private PlanService planService;

    /**
     * A breather between one slot finishing and the next starting.
     *
     * <p>Short now that slots are drafted in turn rather than fired off together: the wait for
     * the previous slot is what spaces the model calls out, so this only exists to give the
     * frontend a beat in which the finished slot is visibly finished before the next one takes
     * over as the live one.
     */
    @Value("${app.plans.draft-stagger-ms:1000}")
    private long staggerMs;

    /** How often to ask whether the slot being drafted has finished. */
    @Value("${app.plans.draft-poll-interval-ms:3000}")
    private long pollIntervalMs;

    /**
     * How long to wait for one slot before giving up on it and moving to the next.
     *
     * <p>A campaign must not be held hostage by a single wedged run. Fifteen minutes is well
     * past a slow roundtable (a handful of minutes, even with every persona taking its turn)
     * but short enough that a stuck slot costs the rest of the campaign one delay rather than
     * the whole evening. Nothing is lost when it trips: the slot keeps whatever status it
     * reached, and {@link PlanScheduler}'s daily sweep still picks up anything left
     * {@code planned}.
     */
    @Value("${app.plans.draft-wait-timeout-ms:900000}")
    private long waitTimeoutMs;

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
            String taskId = null;
            try {
                taskId = taskIdOf(planService.executePlanItem(planId, itemId, null));
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

            // Wait this slot out before commissioning the next. A slot that never started
            // has nothing to wait for, so the campaign moves straight on to the one after.
            if (taskId != null && !awaitDraft(planId, itemId, taskId)) {
                log.warn("[PlanCampaignDrafter] Plan {}: interrupted after {} slot(s); the daily "
                        + "job will pick up the rest", planId, started);
                return;
            }

            if (!sleep(staggerMs)) {
                log.warn("[PlanCampaignDrafter] Plan {}: interrupted after {} slot(s); the daily "
                        + "job will pick up the rest", planId, started);
                return;
            }
        }

        log.info("[PlanCampaignDrafter] Plan {}: {} of {} slot(s) drafted", planId, started, pending.size());
    }

    /** The task id the LLM service assigned to a slot's run, or null if it reported none. */
    @SuppressWarnings("unchecked")
    private static String taskIdOf(Map<String, Object> executeResponse) {
        if (executeResponse == null) {
            return null;
        }
        Object task = executeResponse.get("task");
        if (!(task instanceof Map)) {
            return null;
        }
        Object taskId = ((Map<String, Object>) task).get("task_id");
        return taskId == null ? null : String.valueOf(taskId);
    }

    /**
     * Blocks until a slot's run stops running, or the wait times out.
     *
     * <p>"Stops running" means the copy exists — the run has reached its human gate
     * ({@code awaiting_review}), finished, or failed. It deliberately does NOT mean the user
     * has approved anything: waiting on a person would stall the campaign the moment they
     * closed the tab, and the whole point of drafting on confirm is that the review can happen
     * whenever they like.
     *
     * <p>A task the service cannot describe is treated as finished rather than retried — the
     * campaign moving on is always better than it stopping, and the daily sweep is the net.
     *
     * @return false if the wait was interrupted (shutdown), meaning we should stop entirely.
     */
    private boolean awaitDraft(String planId, String itemId, String taskId) {
        long deadline = System.currentTimeMillis() + waitTimeoutMs;

        while (System.currentTimeMillis() < deadline) {
            if (!sleep(pollIntervalMs)) {
                return false;
            }
            String status;
            try {
                Map<String, Object> task = planService.getTask(taskId);
                status = task == null ? null : String.valueOf(task.get("status"));
            } catch (Exception e) {
                log.info("[PlanCampaignDrafter] Plan {} item {}: task {} unreadable ({}); moving on",
                        planId, itemId, taskId, e.getMessage());
                return true;
            }
            if (!"running".equals(status)) {
                log.info("[PlanCampaignDrafter] Plan {} item {} settled as {}",
                        planId, itemId, status);
                return true;
            }
        }

        log.warn("[PlanCampaignDrafter] Plan {} item {}: still running after {}ms; starting the "
                + "next slot anyway", planId, itemId, waitTimeoutMs);
        return true;
    }

    /** @return false if the wait was interrupted (shutdown), meaning we should stop. */
    private boolean sleep(long millis) {
        if (millis <= 0) {
            return true;
        }
        try {
            Thread.sleep(millis);
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
