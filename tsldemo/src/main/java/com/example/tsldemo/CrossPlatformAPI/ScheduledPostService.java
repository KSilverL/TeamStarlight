package com.example.tsldemo.CrossPlatformAPI;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.Business;
import com.example.tsldemo.ScheduledPost;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.Request.ScheduledPostPatchDTO;
import com.example.tsldemo.DTOs.Request.ScheduledPostReqDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.ENUMS.ScheduledPostStatus;
import com.example.tsldemo.SignInAPI.BusinessRepository;

/**
 * Owns the scheduled-post lifecycle for every platform.
 *
 * <p>Scheduling used to be a {@code taskScheduler.schedule(runnable, instant)} call whose only
 * record of the pending post was the runnable sitting in a thread pool's queue. That worked
 * exactly as long as the JVM stayed up and failed silently in every other case. Here the row is
 * written first, a sweeper picks up what is due, and every outcome — published, retried, failed
 * — is written back so the calendar can show the truth.
 */
@Service
public class ScheduledPostService {

    private static final Logger log = LoggerFactory.getLogger(ScheduledPostService.class);

    /** Attempts per post before giving up. Covers a brief platform blip, not a broken token. */
    private static final int MAX_ATTEMPTS = 3;

    /** Gap between attempts. Short enough that all three finish well inside the missed-window
     * cutoff below, so a retrying post is never failed for being stale mid-retry. */
    private static final Duration RETRY_BACKOFF = Duration.ofMinutes(5);

    /** A row claimed but never resolved — the app died between the claim and the outcome. After
     * this long, put it back so the next sweep can retry it rather than leaving it stranded. */
    private static final Duration STUCK_PUBLISHING_CUTOFF = Duration.ofMinutes(30);

    /** Graph will not accept a scheduled_publish_time closer than 10 minutes out. */
    private static final Duration META_MIN_LEAD = Duration.ofMinutes(10);

    /** Graph's upper bound on scheduled_publish_time is six months. */
    private static final Duration META_MAX_LEAD = Duration.ofDays(180);

    /** How long after its due time to wait before asking Facebook whether a natively-scheduled
     * post actually went live. Graph publishes around the requested moment rather than exactly
     * on it, so checking at the due second would report a perfectly healthy post as unpublished
     * and burn its retries before Facebook had finished. */
    private static final Duration NATIVE_VERIFY_DELAY = Duration.ofMinutes(5);

    @Autowired
    private ScheduledPostRepository scheduledPostRepository;

    @Autowired
    private CrossPlatformService crossPlatformService;

    @Autowired
    private BusinessRepository businessRepository;

    /** Optional so the scheduler still runs in a dev setup with no mail configured — a failed
     * post must still be recorded even if nobody can be emailed about it. */
    @Autowired(required = false)
    private JavaMailSender mailSender;

    /** The zone a bare wall-clock time is interpreted in when the caller doesn't say. Matches
     * the zone PlanScheduler already runs its daily check in. */
    @Value("${app.timezone:Europe/Dublin}")
    private String defaultTimezone;

    /** How late is too late. A post whose time passed while the app was down is failed rather
     * than published: publishing "Happy Friday" on Monday morning is worse than not publishing
     * it, and the user gets told either way. */
    @Value("${app.scheduling.missed-cutoff-minutes:360}")
    private long missedCutoffMinutes;

    public ZoneId defaultZone() {
        return ZoneId.of(defaultTimezone);
    }

    //////////////////////////////////////////////////////// CRUD ////////////////////////////////////////////////////////

    public ScheduledPost create(long businessId, ScheduledPostReqDTO request) {
        return create(businessId, request, null, null);
    }

    /**
     * @param sourcePlanId the posting-plan slot this came from, or null when the post was
     *                     created directly. Recorded so the plan handoff can tell an already
     *                     scheduled slot from a new one.
     */
    public ScheduledPost create(long businessId, ScheduledPostReqDTO request,
                                String sourcePlanId, String sourceItemId) {
        PlatformEnum platform = parsePlatform(request.platform());
        String message = requireMessage(request.message());
        ZoneId zone = parseZone(request.timezone());
        Instant scheduledAt = resolveInstant(request.scheduledTime(), zone);

        requireFuture(scheduledAt);

        Long[] pageIds = toPageIds(request.pageIds());
        if (platform == PlatformEnum.META && pageIds.length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Pick at least one Facebook Page to schedule this post to.");
        }

        ScheduledPost post = new ScheduledPost();
        post.setBusinessId(businessId);
        post.setPlatform(platform);
        post.setScheduledAt(scheduledAt);
        post.setNextAttemptAt(scheduledAt);
        post.setTimezone(zone.getId());
        post.setMessage(message);
        post.setHashtags(toHashtags(request.hashtags()));
        post.setPageIds(pageIds);
        post.setStatus(ScheduledPostStatus.SCHEDULED);
        post.setAttempts(0);
        post.setSourcePlanId(sourcePlanId);
        post.setSourceItemId(sourceItemId);
        post.setCreatedAt(Instant.now());
        post.setUpdatedAt(Instant.now());

        // Facebook can hold the schedule itself, which is strictly better than us holding it:
        // it survives our restarts entirely and stays correct even if this service is down at
        // publish time. Hand it over whenever Graph's own lead-time bounds allow, and fall back
        // to the sweeper when they don't (e.g. "post in 5 minutes", which Graph rejects).
        if (platform == PlatformEnum.META && withinMetaNativeWindow(scheduledAt)) {
            List<String> postIds = crossPlatformService.scheduleToMeta(
                    businessId, pageIds, fullText(post), scheduledAt);
            post.setNativeScheduled(true);
            post.setPlatformPostIds(postIds.toArray(String[]::new));
            // Nothing for the sweeper to publish — its only job here is to confirm afterwards
            // that Facebook did, so it looks a few minutes after the fact rather than at the
            // due moment itself.
            post.setNextAttemptAt(scheduledAt.plus(NATIVE_VERIFY_DELAY));
        }

        ScheduledPost saved = scheduledPostRepository.save(post);
        log.info("Scheduled post {} for business {} on {} at {} ({}{})",
                saved.getId(), businessId, platform, scheduledAt, zone.getId(),
                saved.isNativeScheduled() ? ", held by the platform" : ", swept");
        return saved;
    }

    public List<ScheduledPost> list(long businessId, Instant from, Instant to) {
        if (from != null && to != null) {
            if (to.isBefore(from)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "\"to\" must be on or after \"from\".");
            }
            return scheduledPostRepository
                    .findByBusinessIdAndScheduledAtBetweenOrderByScheduledAtAsc(businessId, from, to);
        }
        return scheduledPostRepository.findByBusinessIdOrderByScheduledAtAsc(businessId);
    }

    public ScheduledPost get(long businessId, long id) {
        return scheduledPostRepository.findByIdAndBusinessId(id, businessId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "No scheduled post found with id " + id + "."));
    }

    public ScheduledPost update(long businessId, long id, ScheduledPostPatchDTO patch) {
        ScheduledPost post = get(businessId, id);
        requireEditable(post, "updated");

        boolean timeChanged = false;
        boolean contentChanged = false;

        if (patch.message() != null) {
            post.setMessage(requireMessage(patch.message()));
            contentChanged = true;
        }
        if (patch.hashtags() != null) {
            post.setHashtags(toHashtags(patch.hashtags()));
            contentChanged = true;
        }
        if (patch.scheduledTime() != null) {
            ZoneId zone = patch.timezone() != null ? parseZone(patch.timezone())
                    : parseZone(post.getTimezone());
            Instant scheduledAt = resolveInstant(patch.scheduledTime(), zone);
            requireFuture(scheduledAt);
            post.setScheduledAt(scheduledAt);
            post.setNextAttemptAt(post.isNativeScheduled()
                    ? scheduledAt.plus(NATIVE_VERIFY_DELAY)
                    : scheduledAt);
            post.setTimezone(zone.getId());
            // A reschedule is a fresh start, not a continuation of a failed run.
            post.setAttempts(0);
            post.setLastError(null);
            timeChanged = true;
        }

        // Changing the Pages after a native schedule exists would orphan the posts already
        // sitting on the old Pages, and re-placing them is a different operation than editing.
        if (patch.pageIds() != null && !post.isNativeScheduled()) {
            Long[] pageIds = toPageIds(patch.pageIds());
            if (post.getPlatform() == PlatformEnum.META && pageIds.length == 0) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "A Facebook post needs at least one Page.");
            }
            post.setPageIds(pageIds);
        } else if (patch.pageIds() != null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "Facebook is already holding this post for its Page(s). Cancel it and schedule "
                    + "a new one to publish to different Pages.");
        }

        // Facebook is holding the real schedule, so an edit here has to reach Graph or the row
        // and the thing that actually publishes would silently disagree.
        if (post.isNativeScheduled()) {
            if (timeChanged) {
                if (!withinMetaNativeWindow(post.getScheduledAt())) {
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                            "Facebook needs a scheduled post to be at least 10 minutes and at most "
                            + "6 months out. Pick another time, or cancel and post it now.");
                }
                crossPlatformService.rescheduleMetaPosts(businessId, post.getPageIds(),
                        post.getPlatformPostIds(), post.getScheduledAt());
            }
            if (contentChanged) {
                crossPlatformService.updateScheduledMetaPosts(businessId, post.getPageIds(),
                        post.getPlatformPostIds(), fullText(post));
            }
        }

        post.setUpdatedAt(Instant.now());
        return scheduledPostRepository.save(post);
    }

    public void cancel(long businessId, long id) {
        ScheduledPost post = get(businessId, id);
        requireEditable(post, "cancelled");

        // Delete the Graph-side post first. If that fails we must not mark the row cancelled —
        // Facebook would publish it anyway and the calendar would claim it never existed.
        if (post.isNativeScheduled()) {
            crossPlatformService.cancelScheduledMetaPosts(businessId, post.getPageIds(),
                    post.getPlatformPostIds());
        }

        post.setStatus(ScheduledPostStatus.CANCELLED);
        post.setUpdatedAt(Instant.now());
        scheduledPostRepository.save(post);
        log.info("Cancelled scheduled post {} for business {}", id, businessId);
    }

    //////////////////////////////////////////////////////// SWEEP ////////////////////////////////////////////////////////

    /**
     * Publishes everything that has come due. Called on a fixed interval by
     * {@link ScheduledPostSweeper}; safe to call concurrently with itself.
     */
    public void runDue() {
        recoverStuckClaims();

        Instant now = Instant.now();
        List<Long> dueIds = scheduledPostRepository.findDueIds(ScheduledPostStatus.SCHEDULED, now);
        if (dueIds.isEmpty()) {
            return;
        }
        log.info("[ScheduledPostSweeper] {} post(s) due", dueIds.size());

        for (Long id : dueIds) {
            // Whoever wins this update owns the post; everyone else moves on. One failing post
            // must not stop the rest of the batch, hence the per-post catch.
            if (scheduledPostRepository.claim(id, ScheduledPostStatus.SCHEDULED,
                    ScheduledPostStatus.PUBLISHING, Instant.now()) != 1) {
                continue;
            }
            try {
                processClaimed(id);
            } catch (Exception e) {
                log.error("[ScheduledPostSweeper] Unhandled error on post {}: {}", id, e.toString(), e);
                scheduledPostRepository.findById(id).ifPresent(
                        post -> recordFailure(post, e.getMessage() == null ? e.toString() : e.getMessage()));
            }
        }
    }

    private void processClaimed(long id) {
        ScheduledPost post = scheduledPostRepository.findById(id).orElse(null);
        if (post == null) {
            return;
        }

        // The missed-window rule is about us failing to publish on time. A natively-scheduled
        // post was Facebook's to publish and it did so at the right moment regardless of how
        // long we were down — arriving late to confirm that is not a failure, so this only
        // applies to the posts the sweeper itself is responsible for publishing.
        Duration lateBy = Duration.between(post.getScheduledAt(), Instant.now());
        if (!post.isNativeScheduled() && lateBy.toMinutes() > missedCutoffMinutes) {
            post.setStatus(ScheduledPostStatus.FAILED);
            post.setLastError("Missed its scheduled time by " + lateBy.toHours() + "h — the service was "
                    + "not running when it came due, and it was too late to publish it as if it were on time.");
            post.setUpdatedAt(Instant.now());
            scheduledPostRepository.save(post);
            notifyFailure(post);
            log.warn("[ScheduledPostSweeper] Post {} missed its window by {}", id, lateBy);
            return;
        }

        try {
            List<String> platformPostIds = publish(post);
            post.setStatus(ScheduledPostStatus.PUBLISHED);
            post.setPlatformPostIds(platformPostIds.toArray(String[]::new));
            post.setLastError(null);
            post.setUpdatedAt(Instant.now());
            scheduledPostRepository.save(post);
            log.info("[ScheduledPostSweeper] Published post {} to {} as {}",
                    id, post.getPlatform(), platformPostIds);
        } catch (Exception e) {
            recordFailure(post, describe(e));
        }
    }

    /** Actually pushes the post to its platform, returning the platform's own post ids. */
    private List<String> publish(ScheduledPost post) {
        // A natively-scheduled post has already been published by Facebook itself — there is
        // nothing to send. Confirm the outcome instead of assuming it, so a post Graph silently
        // dropped shows as failed rather than as a success that never happened.
        if (post.isNativeScheduled()) {
            String problem = crossPlatformService.verifyMetaPostsPublished(
                    post.getBusinessId(), post.getPageIds(), post.getPlatformPostIds());
            if (problem != null) {
                throw new IllegalStateException(problem);
            }
            return List.of(post.getPlatformPostIds());
        }

        return switch (post.getPlatform()) {
            case LINKEDIN -> List.of(crossPlatformService.postToLinkedIn(
                    post.getBusinessId().intValue(),
                    new LinkedInPostReqDTO(fullText(post), null)));
            case META -> crossPlatformService.publishTextToMeta(
                    post.getBusinessId(), post.getPageIds(), fullText(post));
            default -> throw new IllegalStateException(
                    "Scheduling is not supported for " + post.getPlatform() + " yet.");
        };
    }

    /** Books another attempt, or gives up and tells the user. */
    private void recordFailure(ScheduledPost post, String reason) {
        post.setAttempts(post.getAttempts() + 1);
        post.setLastError(reason);
        post.setUpdatedAt(Instant.now());

        if (post.getAttempts() < MAX_ATTEMPTS) {
            // Back to SCHEDULED with a later nextAttemptAt — scheduledAt stays put so the
            // calendar keeps showing the time the user chose, not the retry time.
            post.setStatus(ScheduledPostStatus.SCHEDULED);
            post.setNextAttemptAt(Instant.now().plus(RETRY_BACKOFF));
            scheduledPostRepository.save(post);
            log.warn("[ScheduledPostSweeper] Post {} attempt {}/{} failed, retrying at {}: {}",
                    post.getId(), post.getAttempts(), MAX_ATTEMPTS, post.getNextAttemptAt(), reason);
            return;
        }

        post.setStatus(ScheduledPostStatus.FAILED);
        scheduledPostRepository.save(post);
        log.error("[ScheduledPostSweeper] Post {} failed after {} attempts: {}",
                post.getId(), post.getAttempts(), reason);
        notifyFailure(post);
    }

    /** Returns rows abandoned mid-publish to SCHEDULED so the next sweep retries them. */
    private void recoverStuckClaims() {
        List<ScheduledPost> stuck = scheduledPostRepository.findByStatusAndUpdatedAtBefore(
                ScheduledPostStatus.PUBLISHING, Instant.now().minus(STUCK_PUBLISHING_CUTOFF));

        for (ScheduledPost post : stuck) {
            log.warn("[ScheduledPostSweeper] Post {} was left mid-publish — requeueing", post.getId());
            post.setStatus(ScheduledPostStatus.SCHEDULED);
            post.setNextAttemptAt(Instant.now());
            post.setUpdatedAt(Instant.now());
            scheduledPostRepository.save(post);
        }
    }

    /** Best-effort — a post that failed to publish is already bad news, and a mail server that
     * is also down must not turn it into an unhandled error in the sweep loop. */
    private void notifyFailure(ScheduledPost post) {
        if (mailSender == null) {
            return;
        }
        try {
            Optional<Business> business = businessRepository.findById(post.getBusinessId().intValue());
            if (business.isEmpty() || business.get().getEmail() == null) {
                return;
            }

            SimpleMailMessage mail = new SimpleMailMessage();
            mail.setTo(business.get().getEmail());
            mail.setSubject("A scheduled post did not go out");
            mail.setText("Your " + describePlatform(post.getPlatform()) + " post scheduled for "
                    + post.getScheduledAt().atZone(parseZone(post.getTimezone()))
                    + " could not be published.\n\nReason: " + post.getLastError()
                    + "\n\nIt is marked as failed in your content calendar, where you can edit and "
                    + "reschedule it.");
            mailSender.send(mail);
        } catch (Exception e) {
            log.error("[ScheduledPostSweeper] Could not email the failure for post {}: {}",
                    post.getId(), e.toString());
        }
    }

    //////////////////////////////////////////////////////// HELPERS ////////////////////////////////////////////////////////

    /** The copy that actually gets published: body plus hashtags, which are stored separately
     * so the calendar can style them but go out as one block of text. */
    public static String fullText(ScheduledPost post) {
        String[] hashtags = post.getHashtags();
        if (hashtags == null || hashtags.length == 0) {
            return post.getMessage();
        }
        return post.getMessage() + "\n\n" + String.join(" ", hashtags);
    }

    /**
     * Turns the caller's time into an instant.
     *
     * <p>An offset-carrying string ("…+01:00", "…Z") is unambiguous and is taken as-is. A bare
     * wall-clock string is resolved against {@code zone} — never against the JVM default, which
     * is UTC in a container and was the source of the hour-off publishes this replaced.
     */
    public static Instant resolveInstant(String scheduledTime, ZoneId zone) {
        if (scheduledTime == null || scheduledTime.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "scheduled_time is required.");
        }
        String value = scheduledTime.trim();
        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (Exception ignored) {
            // Not offset-qualified — fall through and treat it as local wall-clock time.
        }
        try {
            return LocalDateTime.parse(value).atZone(zone).toInstant();
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "scheduled_time must look like \"2026-07-18T10:00:00\" or "
                    + "\"2026-07-18T10:00:00+01:00\" — got \"" + scheduledTime + "\".");
        }
    }

    private ZoneId parseZone(String timezone) {
        if (timezone == null || timezone.isBlank()) {
            return defaultZone();
        }
        try {
            return ZoneId.of(timezone.trim());
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "\"" + timezone + "\" is not a known timezone. Use an IANA name like \"Europe/Dublin\".");
        }
    }

    /** The check the old implementation was missing: {@code taskScheduler.schedule()} runs a
     * past instant immediately, so a mistyped year published straight to the live account. */
    private void requireFuture(Instant scheduledAt) {
        if (!scheduledAt.isAfter(Instant.now())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "That time has already passed — pick a time in the future.");
        }
    }

    private boolean withinMetaNativeWindow(Instant scheduledAt) {
        Duration lead = Duration.between(Instant.now(), scheduledAt);
        return lead.compareTo(META_MIN_LEAD) >= 0 && lead.compareTo(META_MAX_LEAD) <= 0;
    }

    private void requireEditable(ScheduledPost post, String verb) {
        if (post.getStatus() != ScheduledPostStatus.SCHEDULED) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "This post is " + post.getStatus().name().toLowerCase()
                    + " and can no longer be " + verb + ".");
        }
    }

    private static PlatformEnum parsePlatform(String platform) {
        if (platform == null || platform.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "platform is required.");
        }
        return switch (platform.trim().toLowerCase()) {
            case "linkedin" -> PlatformEnum.LINKEDIN;
            // The UI says "facebook" because that is what the user connected; the connection is
            // stored under META because it is one Meta OAuth grant covering several surfaces.
            case "facebook", "meta" -> PlatformEnum.META;
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Scheduling is only supported for LinkedIn and Facebook right now — got \""
                    + platform + "\".");
        };
    }

    private static String requireMessage(String message) {
        if (message == null || message.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "message must not be blank.");
        }
        return message;
    }

    private static String[] toHashtags(List<String> hashtags) {
        if (hashtags == null) {
            return new String[0];
        }
        return hashtags.stream()
                .filter(tag -> tag != null && !tag.isBlank())
                .map(String::trim)
                .toArray(String[]::new);
    }

    private static Long[] toPageIds(List<Long> pageIds) {
        if (pageIds == null) {
            return new Long[0];
        }
        return pageIds.stream()
                .filter(java.util.Objects::nonNull)
                .distinct()
                .sorted(Comparator.naturalOrder())
                .toArray(Long[]::new);
    }

    private static String describePlatform(PlatformEnum platform) {
        return platform == PlatformEnum.META ? "Facebook" : "LinkedIn";
    }

    /** Keeps the platform's own explanation — which names the actual fix — instead of letting a
     * generic wrapper message reach the user's failure email. */
    private static String describe(Exception e) {
        if (e instanceof ResponseStatusException rse && rse.getReason() != null) {
            return rse.getReason();
        }
        return e.getMessage() == null ? e.toString() : e.getMessage();
    }
}
