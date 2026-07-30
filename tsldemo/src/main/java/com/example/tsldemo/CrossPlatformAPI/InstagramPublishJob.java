package com.example.tsldemo.CrossPlatformAPI;

import java.time.Instant;
import java.util.List;

/** State of one in-flight Instagram publish.
 *
 * Instagram transcodes a Reel asynchronously and routinely takes tens of seconds, which is too
 * long to hold an HTTP request open — the browser or the Next.js proxy times out first, and a
 * client-side timeout looks like a failure even when the post goes on to succeed. So publishing
 * returns one of these immediately and the client polls it.
 *
 * {@code businessId} is the owner, recorded so the status endpoint can refuse to report on
 * another business's job. */
public class InstagramPublishJob {

    public enum Status { PENDING, DONE, ERROR }

    private final String id;
    private final long businessId;
    private final Instant createdAt = Instant.now();

    private volatile Status status = Status.PENDING;
    private volatile List<String> mediaIds = List.of();
    private volatile String error;
    /** What the job is doing right now, so a long wait can say so instead of just spinning. */
    private volatile String stage = "Preparing the video";

    public InstagramPublishJob(String id, long businessId) {
        this.id = id;
        this.businessId = businessId;
    }

    public String getId() { return id; }
    public long getBusinessId() { return businessId; }
    public Instant getCreatedAt() { return createdAt; }
    public Status getStatus() { return status; }
    public List<String> getMediaIds() { return mediaIds; }
    public String getError() { return error; }
    public String getStage() { return stage; }

    public void setStage(String stage) { this.stage = stage; }

    public void succeed(List<String> mediaIds) {
        this.mediaIds = List.copyOf(mediaIds);
        this.stage = "Published";
        this.status = Status.DONE;
    }

    public void fail(String error) {
        this.error = error;
        this.status = Status.ERROR;
    }
}
