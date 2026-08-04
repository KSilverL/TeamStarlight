package com.example.tsldemo.CrossPlatformAPI;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Drives {@link ScheduledPostService#runDue()} on a fixed interval.
 *
 * <p>One recurring sweep replaces the old one-timer-per-post approach. A timer only exists in
 * the process that created it, so nothing survived a restart and nothing could be listed,
 * edited or cancelled; a sweep reads the same table the API writes, which means the schedule
 * outlives the process and every pending post is visible as a row.
 *
 * <p>Minute granularity is the trade: a post can publish up to one sweep late. That is well
 * inside what social scheduling needs, and the cost of the alternative — per-post timers that
 * have to be rebuilt and reconciled on every boot — is not worth the seconds it would buy.
 */
@Component
public class ScheduledPostSweeper {

    private static final Logger log = LoggerFactory.getLogger(ScheduledPostSweeper.class);

    @Autowired
    private ScheduledPostService scheduledPostService;

    /**
     * {@code fixedDelay} rather than {@code fixedRate} so a slow sweep (a platform call hanging
     * on its read timeout) delays the next one instead of stacking overlapping sweeps on top of
     * it. The initial delay keeps the first sweep out of the way of application startup.
     */
    @Scheduled(
            fixedDelayString = "${app.scheduling.sweep-interval-ms:60000}",
            initialDelayString = "${app.scheduling.sweep-initial-delay-ms:20000}")
    public void sweep() {
        try {
            scheduledPostService.runDue();
        } catch (Exception e) {
            // An escaping exception would kill this @Scheduled task for the lifetime of the
            // process — every future post would then sit unpublished with nothing in the logs
            // to say why. Swallow it here so the next tick still runs.
            log.error("[ScheduledPostSweeper] Sweep failed: {}", e.toString(), e);
        }
    }
}
