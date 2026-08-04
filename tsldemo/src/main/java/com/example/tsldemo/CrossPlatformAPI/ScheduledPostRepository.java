package com.example.tsldemo.CrossPlatformAPI;

import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

import com.example.tsldemo.ENUMS.PlatformEnum;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.example.tsldemo.ScheduledPost;
import com.example.tsldemo.ENUMS.ScheduledPostStatus;

import jakarta.transaction.Transactional;

public interface ScheduledPostRepository extends JpaRepository<ScheduledPost, Long> {

    /** Every scheduled post for one business, oldest first. */
    List<ScheduledPost> findByBusinessIdOrderByScheduledAtAsc(Long businessId);

    /** The calendar's month query. */
    List<ScheduledPost> findByBusinessIdAndScheduledAtBetweenOrderByScheduledAtAsc(
            Long businessId, Instant from, Instant to);

    /** Always look a post up with its owner, never by id alone — otherwise any logged-in
     * business could read or cancel another's posts by guessing a sequential id. */
    Optional<ScheduledPost> findByIdAndBusinessId(Long id, Long businessId);

    @Query("SELECT p.id FROM ScheduledPost p WHERE p.status = :status AND p.nextAttemptAt <= :now ORDER BY p.nextAttemptAt ASC")
    List<Long> findDueIds(@Param("status") ScheduledPostStatus status, @Param("now") Instant now);

    /**
     * Takes ownership of one row by moving it out of {@code from} in a single conditional
     * UPDATE, returning 1 if this caller won it and 0 if someone else already had it.
     *
     * <p>Read-then-write would let two overlapping sweeps — or two app instances behind a load
     * balancer — both see the same row as due and publish it twice. Letting the database decide
     * the winner makes double-publishing impossible without a distributed lock.
     */
    // clearAutomatically so the entity the sweeper loads straight after winning the claim is
    // read back from the database rather than served stale from the persistence context — it
    // would otherwise still show the pre-claim status and get saved back over the claim.
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("UPDATE ScheduledPost p SET p.status = :to, p.updatedAt = :now WHERE p.id = :id AND p.status = :from")
    int claim(@Param("id") Long id,
              @Param("from") ScheduledPostStatus from,
              @Param("to") ScheduledPostStatus to,
              @Param("now") Instant now);

    /** Rows stuck mid-publish because the app died between the claim and the outcome. */
    List<ScheduledPost> findByStatusAndUpdatedAtBefore(ScheduledPostStatus status, Instant before);

    /**
     * Has this plan slot already produced a live post for this platform?
     *
     * <p>Guards the approval handoff against double-scheduling — approving twice, or a retried
     * request, must not put the same copy on the feed twice. Cancelled and failed rows are
     * excluded by the caller's status list, so deliberately cancelling a post and re-running
     * the handoff still works.
     */
    boolean existsByBusinessIdAndSourcePlanIdAndSourceItemIdAndPlatformAndStatusIn(
            Long businessId, String sourcePlanId, String sourceItemId,
            PlatformEnum platform, Collection<ScheduledPostStatus> statuses);

    /**
     * Has this plan slot ever produced a post for this platform, whatever became of it?
     *
     * <p>What the automatic sweep asks, and deliberately blunter than the check above. A
     * cancelled post is a decision the user made on the calendar; a sweep that only skipped
     * <em>live</em> posts would read that empty slot as work outstanding and put the post
     * straight back, every couple of minutes, until they gave up. The explicit handoff keeps
     * the narrower check, so re-scheduling a cancelled slot on purpose still works.
     */
    boolean existsByBusinessIdAndSourcePlanIdAndSourceItemIdAndPlatform(
            Long businessId, String sourcePlanId, String sourceItemId, PlatformEnum platform);

    /** Every post a plan slot produced, for the link-back on the plan view. */
    List<ScheduledPost> findByBusinessIdAndSourcePlanIdOrderByScheduledAtAsc(
            Long businessId, String sourcePlanId);
}
