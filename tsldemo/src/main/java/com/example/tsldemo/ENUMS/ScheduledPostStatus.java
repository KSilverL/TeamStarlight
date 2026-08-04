package com.example.tsldemo.ENUMS;

/** Lifecycle of a row in {@code scheduled_post}.
 *
 * <p>{@code PUBLISHING} is the claim marker: the sweeper flips a due row into it with a
 * conditional update before doing any work, so a second sweep (or a second app instance) can
 * never pick up the same post twice. Every terminal state is reachable from it. */
public enum ScheduledPostStatus {
    /** Waiting for its publish time. The only state that can be edited or cancelled. */
    SCHEDULED,
    /** Claimed by a sweep and currently being published. Transient. */
    PUBLISHING,
    /** Live on the platform. Kept as an audit record. */
    PUBLISHED,
    /** Every attempt failed, or the post missed its window while the app was down. */
    FAILED,
    /** Cancelled by the user before it fired. */
    CANCELLED
}
