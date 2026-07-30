package com.example.tsldemo.CrossPlatformAPI;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

/** Tracks in-flight Instagram publishes so the client can poll instead of holding a request open.
 *
 * Deliberately in-memory. These jobs live for seconds to minutes and exist only so the UI can
 * report progress — nothing downstream depends on them, so the cost of a restart is that the UI
 * loses track of a publish, not that the publish is lost or repeated. Two consequences worth
 * knowing before this runs on more than one instance:
 *
 *  - a restart mid-publish leaves the post to complete on Instagram's side with no local record,
 *    so the UI will show it as unknown rather than posted;
 *  - with more than one backend replica, a poll can land on an instance that never saw the job.
 *
 * Move this to a table if either becomes real. */
@Component
public class InstagramPublishJobStore {

    /** Finished jobs are kept briefly so a slow client can still read the outcome, then dropped —
     * without this the map is a slow leak for the lifetime of the process. */
    private static final Duration RETENTION = Duration.ofHours(1);

    private final ConcurrentHashMap<String, InstagramPublishJob> jobs = new ConcurrentHashMap<>();

    public InstagramPublishJob create(long businessId) {
        evictExpired();
        String id = UUID.randomUUID().toString();
        InstagramPublishJob job = new InstagramPublishJob(id, businessId);
        jobs.put(id, job);
        return job;
    }

    /** Looks up a job, refusing anything that isn't this business's own.
     *
     * A job that belongs to someone else is reported as "not found" rather than "forbidden" on
     * purpose: distinguishing the two would confirm that a given job id exists. */
    public InstagramPublishJob requireOwned(String jobId, long businessId) {
        InstagramPublishJob job = jobs.get(jobId);
        if (job == null || job.getBusinessId() != businessId) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "No such Instagram publish job. It may have finished more than an hour ago, or the "
                    + "backend may have restarted while it was running — check the account before "
                    + "retrying, or a duplicate may be posted.");
        }
        return job;
    }

    private void evictExpired() {
        Instant cutoff = Instant.now().minus(RETENTION);
        jobs.values().removeIf(job -> job.getStatus() != InstagramPublishJob.Status.PENDING
                && job.getCreatedAt().isBefore(cutoff));
    }
}
