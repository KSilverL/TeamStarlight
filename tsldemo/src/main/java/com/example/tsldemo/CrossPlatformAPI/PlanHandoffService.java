package com.example.tsldemo.CrossPlatformAPI;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.ScheduledPost;
import com.example.tsldemo.DTOs.Request.ScheduledPostReqDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.ScheduledPostRespDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.ENUMS.ScheduledPostStatus;

/**
 * Turns the approved copy for a posting-plan slot into scheduled posts.
 *
 * <p>This is the seam between the two halves of the system. A plan says <em>what</em> to post
 * and roughly <em>when</em>; the workflow produces the copy and stops at the human gate; and
 * until now nothing carried an approved draft across into something that actually publishes —
 * a plan item reaching {@code done} meant "content was produced and approved", not "posted".
 *
 * <p>Two constraints shape the design:
 * <ul>
 *   <li><b>Copy must be captured at approval time.</b> The LLM service holds tasks in an
 *       in-memory registry, so its {@code outputs} do not survive a restart. There is no
 *       "collect it later" option — whatever this reads has to be written to the database now.</li>
 *   <li><b>Per-platform partial success is normal.</b> One slot can target platforms we cannot
 *       publish to, and a slot approved after its window has passed can no longer be scheduled.
 *       Neither should cost the caller the platforms that did work, so every platform is
 *       reported individually rather than failing the whole handoff.</li>
 * </ul>
 */
@Service
public class PlanHandoffService {

    private static final Logger log = LoggerFactory.getLogger(PlanHandoffService.class);

    /** A slot already has a post for this platform if one exists in any of these states —
     * cancelled and failed are excluded so cancelling and re-running the handoff works. */
    private static final Set<ScheduledPostStatus> LIVE_STATUSES = Set.of(
            ScheduledPostStatus.SCHEDULED,
            ScheduledPostStatus.PUBLISHING,
            ScheduledPostStatus.PUBLISHED);

    /**
     * How far ahead a publish moment has to be to count as schedulable.
     *
     * <p>Not zero, for two reasons: {@code ScheduledPostService} rejects a time already gone,
     * and the seconds between computing a moment and saving the row would make a slot "one
     * minute out" fail validation for no reason the user could understand. Fifteen minutes
     * also clears Facebook's own ten-minute floor for native scheduling, so a rescheduled post
     * still gets handed to Graph rather than falling back to the sweeper.
     */
    private static final Duration MIN_LEAD = Duration.ofMinutes(15);

    @Autowired
    private PlanService planService;

    @Autowired
    private ScheduledPostService scheduledPostService;

    @Autowired
    private ScheduledPostRepository scheduledPostRepository;

    @Autowired
    private CrossPlatformRepository crossPlatformRepository;

    /**
     * Schedules every approved platform draft on a plan slot.
     *
     * @param plan            the plan document, already ownership-checked by the caller
     * @param requestedPageIds Facebook Pages to publish to; when empty, falls back to the Pages
     *                         on the business's stored Meta connection (the browser's own
     *                         selection lives in localStorage, which a server-side caller —
     *                         a future automated handoff — has no way to read)
     * @return what was scheduled and what was skipped, with a reason for each skip
     */
    public Map<String, Object> scheduleApprovedItem(
            int businessId, Map<String, Object> plan, String itemId, List<Long> requestedPageIds) {
        return scheduleApprovedItem(
                businessId, plan, itemId, ScheduleOptions.forPages(requestedPageIds));
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> scheduleApprovedItem(
            int businessId, Map<String, Object> plan, String itemId, ScheduleOptions options) {

        String planId = String.valueOf(plan.get("plan_id"));
        Map<String, Object> item = findItem(plan, itemId);

        String taskId = (String) item.get("task_id");
        if (taskId == null || taskId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "This slot hasn't been drafted yet — generate the draft first.");
        }

        Map<String, Object> task = planService.getTask(taskId);
        requireApproved(task, itemId);

        List<Map<String, Object>> outputs =
                (List<Map<String, Object>>) task.getOrDefault("outputs", List.of());
        if (outputs.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "The draft for this slot produced no copy to schedule.");
        }

        String plannedDate = (String) item.get("planned_date");
        String timeOfDay = (String) item.getOrDefault("time_of_day", "");
        LocalDate date = parsePlannedDate(plannedDate);

        List<Map<String, Object>> scheduled = new ArrayList<>();
        List<Map<String, Object>> skipped = new ArrayList<>();

        for (Map<String, Object> output : outputs) {
            String platform = String.valueOf(output.get("platform"));
            try {
                ScheduledPost post = scheduleOne(
                        businessId, planId, itemId, output, date, timeOfDay, options);
                scheduled.add(Map.of(
                        "platform", platform,
                        "scheduled_post_id", String.valueOf(post.getId()),
                        "scheduled_at", post.getScheduledAt().toString()));
            } catch (SkippedPlatform e) {
                skipped.add(Map.of(
                        "platform", platform,
                        "reason", e.getMessage(),
                        // The code, not the prose, is what the UI branches on — only a slot
                        // skipped for TIME_PASSED can be fixed by picking a new time, and
                        // string-matching an English sentence to work that out would break the
                        // moment the wording is improved.
                        "reason_code", e.code()));
            } catch (ResponseStatusException e) {
                // A validation failure on one platform is that platform's problem, not the
                // whole slot's.
                skipped.add(Map.of("platform", platform,
                        "reason", e.getReason() == null ? "Could not schedule." : e.getReason(),
                        "reason_code", SkipCode.ERROR));
            }
        }

        log.info("[PlanHandoff] Plan {} item {}: scheduled {}, skipped {}",
                planId, itemId, scheduled.size(), skipped.size());

        return Map.of(
                "plan_id", planId,
                "item_id", itemId,
                "scheduled", scheduled,
                "skipped", skipped);
    }

    /**
     * Does this slot have approved copy that has not reached the calendar yet?
     *
     * <p>The sweeper's cheap pre-check. Answering from the database alone matters: the real
     * handoff has to fetch the task from the LLM service, and asking that question once per
     * approved slot per sweep would be a steady stream of HTTP calls to answer "no" almost
     * every time.
     *
     * <p>Deliberately per-platform rather than per-slot. A slot that scheduled LinkedIn but
     * skipped Facebook because no Page was connected still has work outstanding, and should
     * start scheduling by itself once that Page is connected.
     *
     * <p>Counts a post in <em>any</em> state as handled, unlike the duplicate guard inside the
     * handoff itself. That guard ignores cancelled posts so a user can deliberately re-run the
     * handoff; applying the same rule here would turn cancelling a post on the calendar into a
     * fight with the sweeper, which would re-create it minutes later.
     */
    @SuppressWarnings("unchecked")
    public boolean needsScheduling(int businessId, String planId, Map<String, Object> item) {
        if (!"done".equals(item.get("status"))) {
            return false;
        }
        String taskId = (String) item.get("task_id");
        if (taskId == null || taskId.isBlank()) {
            return false;
        }

        String itemId = String.valueOf(item.get("item_id"));
        List<String> platforms = (List<String>) item.getOrDefault("platforms", List.of());

        for (String platform : platforms) {
            PlatformEnum target = schedulablePlatform(platform);
            if (target == null) {
                continue;  // nothing we could ever schedule — not outstanding work
            }
            if (!scheduledPostRepository
                    .existsByBusinessIdAndSourcePlanIdAndSourceItemIdAndPlatform(
                            (long) businessId, planId, itemId, target)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Every post a plan's slots have put on the calendar, keyed by item id.
     *
     * <p>What the plan view reads to tell "approved and queued to publish" from "approved and
     * went nowhere". Those two used to render identically, so a slot whose scheduling failed
     * looked exactly like one that had worked.
     */
    public Map<String, List<ScheduledPostRespDTO>> listScheduledByItem(int businessId, String planId) {
        List<ScheduledPost> posts = scheduledPostRepository
                .findByBusinessIdAndSourcePlanIdOrderByScheduledAtAsc((long) businessId, planId);

        Map<String, List<ScheduledPostRespDTO>> byItem = new LinkedHashMap<>();
        for (ScheduledPost post : posts) {
            String itemId = post.getSourceItemId();
            if (itemId == null) {
                // The handoff always writes both ids together, so this should not happen — but a
                // null key would fail JSON serialisation and take the whole plan view down with
                // it, which is a steep price for one unattributable row.
                continue;
            }
            byItem.computeIfAbsent(itemId, key -> new ArrayList<>())
                    .add(ScheduledPostRespDTO.from(post, scheduledPostService.defaultZone()));
        }
        return byItem;
    }

    /** Schedules one platform's approved draft, or throws {@link SkippedPlatform} explaining
     * why this platform is being passed over. */
    private ScheduledPost scheduleOne(
            int businessId, String planId, String itemId, Map<String, Object> output,
            LocalDate date, String timeOfDay, ScheduleOptions options) {

        String platform = String.valueOf(output.get("platform"));

        // A rejected draft is not content to publish — it only appears here because the task
        // records every verdict it saw.
        String decision = String.valueOf(output.getOrDefault("decision", ""));
        if (decision.equalsIgnoreCase("reject")) {
            throw new SkippedPlatform(SkipCode.REJECTED,
                    "The draft for this platform was rejected.");
        }

        PlatformEnum target = schedulablePlatform(platform);
        if (target == null) {
            throw new SkippedPlatform(SkipCode.NO_INTEGRATION,
                    platform + " has no publishing integration yet — the copy "
                    + "is drafted but has to be posted manually.");
        }

        String draft = output.get("draft") == null ? "" : String.valueOf(output.get("draft"));
        if (draft.isBlank()) {
            throw new SkippedPlatform(SkipCode.NO_TEXT,
                    "This platform's draft has no text to publish "
                    + "(media-only drafts can't be scheduled yet).");
        }

        List<Long> pageIds = target == PlatformEnum.META
                ? resolvePageIds(businessId, options.pageIds())
                : List.of();

        if (scheduledPostRepository
                .existsByBusinessIdAndSourcePlanIdAndSourceItemIdAndPlatformAndStatusIn(
                        (long) businessId, planId, itemId, target, LIVE_STATUSES)) {
            throw new SkippedPlatform(SkipCode.ALREADY_SCHEDULED,
                    "Already scheduled for this platform.");
        }

        LocalDateTime publishAt = resolvePublishMoment(date, timeOfDay, platform, options);
        Copy copy = splitHashtags(draft);

        return scheduledPostService.create(
                businessId,
                new ScheduledPostReqDTO(
                        platform,
                        publishAt.toString(),
                        // The plan's times mean the audience's local time, which for this app is
                        // the configured business zone — not the reviewer's browser zone, since
                        // the same slot must mean the same moment whoever approves it.
                        scheduledPostService.defaultZone().getId(),
                        copy.message(),
                        copy.hashtags(),
                        pageIds),
                planId,
                itemId);
    }

    /**
     * When this platform's copy should actually publish.
     *
     * <p>The slot's own date and window is the answer whenever it is still ahead. It often
     * isn't: a plan drafted on Monday and approved on Thursday has Tuesday's slots behind it,
     * and a morning slot approved that same afternoon has missed its window by hours. Before
     * this, every one of those was a dead end — the post was silently dropped with "that time
     * has already passed" and no way forward but re-approving something that would fail again.
     *
     * <p>So a passed slot is a question, not a failure, and there are three answers: the caller
     * names a time, the caller asks us to pick the next sensible one, or — by default — nothing
     * moves and the skip says so, because quietly publishing on a different day than the plan
     * shows is worse than not publishing.
     */
    private LocalDateTime resolvePublishMoment(
            LocalDate date, String timeOfDay, String platform, ScheduleOptions options) {

        LocalDateTime earliest = LocalDateTime.now(scheduledPostService.defaultZone()).plus(MIN_LEAD);

        if (options.hasExplicitTime()) {
            LocalDateTime chosen = parseChosenTime(options.scheduledAt());
            if (chosen.isBefore(earliest)) {
                throw new SkippedPlatform(SkipCode.TIME_PASSED,
                        "That time has already passed — pick one at least a few minutes ahead.");
            }
            return chosen;
        }

        LocalTime time = PostingWindowResolver.resolve(timeOfDay, platform);
        LocalDateTime planned = date.atTime(time);
        if (!planned.isBefore(earliest)) {
            return planned;
        }

        if (options.autoReschedule()) {
            return nextViableSlot(time, earliest);
        }

        throw new SkippedPlatform(SkipCode.TIME_PASSED,
                "Its " + time + " slot on " + date + " has already passed.");
    }

    /**
     * The soonest this slot's own posting window comes round again.
     *
     * <p>Keeps the window the plan chose — a slot planned for the morning stays a morning post
     * — and only moves the day. Jumping straight to "now + 15 minutes" would technically
     * publish it, but at whatever arbitrary hour the approval happened to land, which is the
     * opposite of what a posting plan is for.
     */
    static LocalDateTime nextViableSlot(LocalTime time, LocalDateTime earliest) {
        LocalDateTime candidate = earliest.toLocalDate().atTime(time);
        // Computed from today rather than walked forward from the original date, so a slot
        // missed weeks ago costs one comparison rather than a loop over every day since.
        return candidate.isBefore(earliest) ? candidate.plusDays(1) : candidate;
    }

    private static LocalDateTime parseChosenTime(String scheduledAt) {
        try {
            return LocalDateTime.parse(scheduledAt.trim());
        } catch (Exception e) {
            throw new SkippedPlatform(SkipCode.ERROR,
                    "\"" + scheduledAt + "\" isn't a time we can read (expected "
                    + "2026-08-05T09:00).");
        }
    }

    /**
     * The task has to be finished, not merely reviewed.
     *
     * <p>A slot targeting two platforms stays {@code awaiting_review} until both drafts have a
     * verdict, so this also catches the half-approved case — scheduling then would quietly drop
     * the platform still waiting.
     */
    private void requireApproved(Map<String, Object> task, String itemId) {
        String status = String.valueOf(task.getOrDefault("status", ""));
        if ("completed".equals(status)) {
            return;
        }
        if ("awaiting_review".equals(status)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "This draft is still waiting on a review decision — approve it first.");
        }
        if ("error".equals(status)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "Generating this slot's draft failed, so there is nothing to schedule.");
        }
        throw new ResponseStatusException(HttpStatus.CONFLICT,
                "This slot's draft is still being generated (status: " + status + ") — "
                + "wait for it to finish, then approve it.");
    }

    /**
     * Which Pages a Facebook post should go to.
     *
     * <p>Prefers the caller's explicit selection and falls back to every Page on the connection.
     * The fallback matters because the browser's chosen Pages live in localStorage: an automated
     * handoff has no browser, so without it Facebook slots could only ever be scheduled by a
     * human clicking approve.
     */
    private List<Long> resolvePageIds(int businessId, List<Long> requestedPageIds) {
        if (requestedPageIds != null && !requestedPageIds.isEmpty()) {
            return requestedPageIds;
        }

        CrossPlatformOAuth connection =
                crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.META);
        Long[] stored = connection == null ? null : connection.getPageIdArray();

        if (stored == null || stored.length == 0) {
            throw new SkippedPlatform(SkipCode.NO_PAGES,
                    "No Facebook Page is connected — connect Facebook and load "
                    + "your Pages in the Brand Profile, then schedule this one by hand.");
        }
        return Arrays.asList(stored);
    }

    /** Only the platforms with a real publishing path; anything else is drafted, not scheduled. */
    private static PlatformEnum schedulablePlatform(String platform) {
        if (platform == null) {
            return null;
        }
        return switch (platform.trim().toLowerCase()) {
            case "linkedin" -> PlatformEnum.LINKEDIN;
            case "facebook", "meta" -> PlatformEnum.META;
            default -> null;
        };
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> findItem(Map<String, Object> plan, String itemId) {
        List<Map<String, Object>> items =
                (List<Map<String, Object>>) plan.getOrDefault("items", List.of());
        for (Map<String, Object> item : items) {
            if (itemId.equals(item.get("item_id"))) {
                return item;
            }
        }
        throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                "No item " + itemId + " on this plan.");
    }

    private static LocalDate parsePlannedDate(String plannedDate) {
        try {
            return LocalDate.parse(plannedDate);
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "This slot has no usable planned date (" + plannedDate + ").");
        }
    }

    /** A draft split into the body and its trailing hashtags. Package-private alongside
     * {@link #splitHashtags} so the split can be tested directly — it decides what actually
     * gets published. */
    record Copy(String message, List<String> hashtags) {
    }

    /**
     * Splits trailing hashtags off a draft.
     *
     * <p>The workflow returns one blob of text; the calendar stores and styles hashtags
     * separately. Only a trailing run of hashtag-only lines is taken, so a "#1" inside a
     * sentence stays in the body. Mirrors the same split the Schedule Post modal does for
     * hand-written posts, so a post looks the same however it got there.
     *
     * <p>Publishing re-joins the two with a blank line, so a draft that already ended in a
     * hashtag line publishes byte-identically; one that spread hashtags over several lines gets
     * them collapsed onto one.
     */
    static Copy splitHashtags(String text) {
        List<String> lines = new ArrayList<>(Arrays.asList(text.stripTrailing().split("\n", -1)));
        List<String> hashtags = new ArrayList<>();

        while (!lines.isEmpty()) {
            String line = lines.get(lines.size() - 1).trim();
            if (line.isEmpty()) {
                lines.remove(lines.size() - 1);
                continue;
            }
            String[] tokens = line.split("\\s+");
            boolean allHashtags = Arrays.stream(tokens)
                    .allMatch(t -> t.startsWith("#") && t.length() > 1);
            if (!allHashtags) {
                break;
            }
            hashtags.addAll(0, Arrays.asList(tokens));
            lines.remove(lines.size() - 1);
        }

        // Deduplicate while preserving order — a draft that repeats a tag would otherwise
        // publish it twice once the body and tag block are rejoined.
        Map<String, Boolean> seen = new LinkedHashMap<>();
        for (String tag : hashtags) {
            seen.putIfAbsent(tag, Boolean.TRUE);
        }

        return new Copy(String.join("\n", lines).stripTrailing(),
                new ArrayList<>(seen.keySet()));
    }

    /**
     * Why a platform was passed over, in a form the UI can branch on.
     *
     * <p>Only {@link #TIME_PASSED} is something the user can act on, and only it gets the
     * reschedule controls. Distinguishing it by matching the English message would tie the UI
     * to the exact wording — the first person to improve a sentence would silently remove the
     * only way to recover a missed slot.
     */
    static final class SkipCode {
        static final String REJECTED = "rejected";
        static final String NO_INTEGRATION = "no_integration";
        static final String NO_TEXT = "no_text";
        static final String NO_PAGES = "no_pages";
        static final String ALREADY_SCHEDULED = "already_scheduled";
        static final String TIME_PASSED = "time_passed";
        static final String ERROR = "error";

        private SkipCode() {
        }
    }

    /**
     * How the caller wants this slot scheduled.
     *
     * <p>The two time fields are the answer to a missed slot: name a moment, or ask for the
     * next sensible one. Neither is the default — a post silently moving to a different day
     * than the plan shows is worse than a post that visibly didn't go out.
     *
     * @param pageIds        Facebook Pages to publish to; empty falls back to the connection's
     * @param scheduledAt    an explicit local moment ("2026-08-05T09:00"), or null
     * @param autoReschedule roll a passed slot forward to its next posting window
     */
    public record ScheduleOptions(List<Long> pageIds, String scheduledAt, boolean autoReschedule) {

        public static ScheduleOptions forPages(List<Long> pageIds) {
            return new ScheduleOptions(pageIds, null, false);
        }

        public boolean hasExplicitTime() {
            return scheduledAt != null && !scheduledAt.isBlank();
        }
    }

    /** Signals that one platform is being passed over, carrying the reason shown to the user
     * and the code the UI branches on. Unchecked so it can surface from the helpers without
     * threading a result type through. */
    static class SkippedPlatform extends RuntimeException {
        private final String code;

        SkippedPlatform(String code, String message) {
            super(message);
            this.code = code;
        }

        String code() {
            return code;
        }
    }
}
