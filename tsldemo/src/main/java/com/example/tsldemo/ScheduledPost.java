package com.example.tsldemo;

import java.time.Instant;

import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.ENUMS.ScheduledPostStatus;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

/**
 * A post queued to publish at a future moment.
 *
 * <p>This table is the schedule. The previous implementation held pending posts only in a
 * {@code ThreadPoolTaskScheduler}'s in-memory queue, so a restart, redeploy or crash silently
 * dropped every one of them while the UI still claimed they were scheduled. Persisting the
 * intent and sweeping for due rows means the schedule survives the process that created it.
 *
 * <p>Two publishing models share this table, distinguished by {@link #nativeScheduled}:
 * <ul>
 *   <li><b>Swept</b> (LinkedIn) — we hold the schedule and publish at the due moment.</li>
 *   <li><b>Native</b> (Facebook) — Graph holds the schedule via {@code scheduled_publish_time}
 *       and publishes on its own; the row is a mirror so the calendar has something to show,
 *       and the sweeper only confirms the outcome after the fact.</li>
 * </ul>
 */
@Getter
@Setter
@Entity
@Table(name = "scheduled_post", indexes = {
        // The sweeper's hot query: due rows in a given state.
        @Index(name = "idx_scheduled_post_due", columnList = "status, next_attempt_at"),
        // The calendar's query: one business's month.
        @Index(name = "idx_scheduled_post_business", columnList = "business_id, scheduled_at")
})
public class ScheduledPost {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private Long businessId;

    @Enumerated(EnumType.STRING)
    private PlatformEnum platform;

    /** When the user wants this published, as an absolute instant.
     *
     * <p>Stored as an {@code Instant} rather than the old {@code LocalDateTime} because the
     * previous code resolved the user's wall-clock time against {@code ZoneId.systemDefault()}
     * — the JVM's zone, which is UTC in a container — so a 10:00 post published at 11:00 Irish
     * summer time. The zone is pinned once, at the edge, and never re-guessed after that. */
    private Instant scheduledAt;

    /** The IANA zone the user picked {@link #scheduledAt} in, kept so the calendar can render
     * the same wall-clock time it was chosen at regardless of where the reader is. */
    private String timezone;

    /** When the sweeper should next look at this row. Equal to {@link #scheduledAt} until a
     * failed attempt pushes it out for a retry — kept separate so a retry never rewrites the
     * time the user actually asked for (and the calendar keeps showing that time). */
    private Instant nextAttemptAt;

    @Column(columnDefinition = "TEXT")
    private String message;

    private String[] hashtags;

    /** Facebook Page ids this publishes to. Null/empty for LinkedIn. Index-aligned with
     * {@link #platformPostIds} once a native schedule has been placed. */
    private Long[] pageIds;

    @Enumerated(EnumType.STRING)
    private ScheduledPostStatus status;

    /** True when the platform itself holds the schedule (see the class comment). */
    private boolean nativeScheduled;

    /** Ids returned by the platform — one per Page for Facebook, one element for LinkedIn.
     * Populated at creation time for native schedules, at publish time for swept ones. */
    private String[] platformPostIds;

    /** Why the last attempt failed, verbatim from the platform where possible. Surfaced in the
     * calendar so a failed post says what went wrong rather than just going red. */
    @Column(columnDefinition = "TEXT")
    private String lastError;

    private int attempts;

    private Instant createdAt;

    private Instant updatedAt;
}
