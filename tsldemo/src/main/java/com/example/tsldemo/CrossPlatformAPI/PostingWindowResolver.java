package com.example.tsldemo.CrossPlatformAPI;

import java.time.LocalTime;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Turns a plan item's free-text {@code time_of_day} into a concrete clock time.
 *
 * <p>The planner is deliberately allowed to be vague here — {@code core/plan_schema.py}
 * documents the field as "e.g. 'morning' or '18:00'" — because a campaign plan is strategy,
 * not a publishing queue. Scheduling a post needs an actual {@code HH:mm}, so something has to
 * make that call, and doing it here keeps the planner free to keep speaking in windows.
 *
 * <p>Resolution order, most specific first:
 * <ol>
 *   <li>An explicit time anywhere in the string ("18:00", "6pm", "07:30–09:30" → 07:30).</li>
 *   <li>A named window the platform has its own opinion about ("morning" on LinkedIn → 08:00,
 *       inside the 07:30–09:30 window {@code skills/posting_plan.md} recommends).</li>
 *   <li>The same name resolved generically ("evening" → 19:00) for platforms with no specific
 *       window for it — better to honour the word the planner used than to silently substitute
 *       an unrelated hour.</li>
 *   <li>The platform's best default, when the field is blank or unreadable.</li>
 * </ol>
 *
 * <p>The per-platform times mirror the windows in {@code LLM_service/skills/posting_plan.md}.
 * That file is the tuning surface for the planner's own advice; if the windows there change,
 * change them here too — they are two halves of one decision.
 */
public final class PostingWindowResolver {

    private PostingWindowResolver() {
    }

    /** Used when the platform is unknown and the field gives us nothing to work with. */
    private static final LocalTime FALLBACK = LocalTime.of(9, 0);

    /** Named windows for platforms that have a documented preference for them. */
    private static final Map<String, Map<String, LocalTime>> PLATFORM_WINDOWS = Map.of(
            // Tue/Wed/Thu mornings (07:30–09:30) or lunch (11:30–13:00). B2B, weekdays.
            "linkedin", Map.of(
                    "morning", LocalTime.of(8, 0),
                    "midday", LocalTime.of(12, 0),
                    "afternoon", LocalTime.of(12, 0)),
            // Weekday mid-mornings (09:00–11:00) and early afternoons (13:00–15:00).
            "facebook", Map.of(
                    "morning", LocalTime.of(9, 30),
                    "midday", LocalTime.of(13, 30),
                    "afternoon", LocalTime.of(13, 30)),
            // Weekday evenings (18:00–21:00) and weekend late mornings (10:00–12:00).
            "instagram", Map.of(
                    "morning", LocalTime.of(11, 0),
                    "evening", LocalTime.of(19, 0)),
            // Commute peaks: 08:00–09:00 and 17:00–18:00.
            "x", Map.of(
                    "morning", LocalTime.of(8, 30),
                    "evening", LocalTime.of(17, 30)),
            // Early morning (06:00–09:00) and evening (19:00–23:00).
            "tiktok", Map.of(
                    "morning", LocalTime.of(7, 0),
                    "evening", LocalTime.of(20, 0)));

    /** The single best slot per platform, used when the item names no window at all. */
    private static final Map<String, LocalTime> PLATFORM_DEFAULTS = Map.of(
            "linkedin", LocalTime.of(8, 0),
            "facebook", LocalTime.of(9, 30),
            "instagram", LocalTime.of(19, 0),
            "x", LocalTime.of(8, 30),
            "tiktok", LocalTime.of(20, 0));

    /** Plain-English windows, for names a platform expresses no preference about. */
    private static final Map<String, LocalTime> GENERIC_WINDOWS = Map.of(
            "morning", LocalTime.of(9, 0),
            "midday", LocalTime.of(12, 0),
            "afternoon", LocalTime.of(14, 0),
            "evening", LocalTime.of(19, 0),
            "night", LocalTime.of(21, 0));

    /**
     * Matches the first clock-like token in the string.
     *
     * <p>Anchored on a word boundary and rejecting a trailing digit so a bare "2026" or an
     * ordinal can't be read as a time. A range ("07:30–09:30") matches its start, which is the
     * right end of a posting window to aim for.
     */
    private static final Pattern EXPLICIT_TIME =
            Pattern.compile("\\b(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)?\\b(?!\\d)");

    /**
     * @param timeOfDay the plan item's {@code time_of_day}; may be null, blank or vague
     * @param platform  the target platform, e.g. "linkedin" (case-insensitive; "twitter" and
     *                  "meta" are accepted as aliases)
     * @return a concrete time — never null, so a caller can always build a publish moment
     */
    public static LocalTime resolve(String timeOfDay, String platform) {
        String key = normalisePlatform(platform);
        String raw = timeOfDay == null ? "" : timeOfDay.trim().toLowerCase();

        LocalTime explicit = parseExplicit(raw);
        if (explicit != null) {
            return explicit;
        }

        String window = namedWindow(raw);
        if (window != null) {
            LocalTime platformSpecific = PLATFORM_WINDOWS
                    .getOrDefault(key, Map.of())
                    .get(window);
            if (platformSpecific != null) {
                return platformSpecific;
            }
            return GENERIC_WINDOWS.get(window);
        }

        return PLATFORM_DEFAULTS.getOrDefault(key, FALLBACK);
    }

    /** True when the item named a real time rather than leaving it to the defaults — lets a
     * caller report whether a slot's time was the planner's choice or ours. */
    public static boolean isExplicit(String timeOfDay) {
        String raw = timeOfDay == null ? "" : timeOfDay.trim().toLowerCase();
        return parseExplicit(raw) != null || namedWindow(raw) != null;
    }

    /** The frontend and the plan schema disagree on some platform names; fold them together
     * so "Twitter", "X" and "meta" don't each miss the table and fall to the generic default. */
    private static String normalisePlatform(String platform) {
        if (platform == null) {
            return "";
        }
        String key = platform.trim().toLowerCase();
        return switch (key) {
            case "twitter", "twitter/x" -> "x";
            case "meta" -> "facebook";
            default -> key;
        };
    }

    private static LocalTime parseExplicit(String raw) {
        if (raw.isEmpty()) {
            return null;
        }

        Matcher matcher = EXPLICIT_TIME.matcher(raw);
        while (matcher.find()) {
            String minuteGroup = matcher.group(2);
            String meridiem = matcher.group(3);

            // A bare number is not a time. "2 posts a week" would otherwise resolve to 02:00
            // and silently publish at 2am, so require the shape of a clock: either minutes
            // ("18:00") or a meridiem ("6pm"). Keep scanning — a real time may follow.
            if (minuteGroup == null && meridiem == null) {
                continue;
            }

            int hour;
            int minute;
            try {
                hour = Integer.parseInt(matcher.group(1));
                minute = minuteGroup == null ? 0 : Integer.parseInt(minuteGroup);
            } catch (NumberFormatException e) {
                continue;
            }

            if (meridiem != null) {
                if (hour < 1 || hour > 12) {
                    continue;
                }
                // 12am is midnight and 12pm is noon — the one hour where the arithmetic inverts.
                if (hour == 12) {
                    hour = 0;
                }
                if (meridiem.equals("pm")) {
                    hour += 12;
                }
            }

            // Out of clock range means it was never a time; let a later match, or the named
            // window, decide instead of clamping a wrong number into a real publish slot.
            if (hour > 23 || minute > 59) {
                continue;
            }
            return LocalTime.of(hour, minute);
        }
        return null;
    }

    /** Maps the vocabulary the planner actually uses onto the five canonical windows. */
    private static String namedWindow(String raw) {
        if (raw.isEmpty()) {
            return null;
        }
        // Checked before "morning"/"afternoon" so "late morning" still reads as morning but
        // "lunchtime" doesn't get missed by a plain contains("noon") on "afternoon".
        if (raw.contains("lunch") || raw.contains("midday") || raw.contains("mid-day")) {
            return "midday";
        }
        if (raw.contains("morning") || raw.contains("breakfast")) {
            return "morning";
        }
        if (raw.contains("afternoon")) {
            return "afternoon";
        }
        if (raw.contains("evening") || raw.contains("dinner")) {
            return "evening";
        }
        if (raw.contains("night") || raw.contains("late")) {
            return "night";
        }
        // "noon" last: "afternoon" contains it, and reaching here means that already failed.
        if (raw.contains("noon")) {
            return "midday";
        }
        return null;
    }
}
