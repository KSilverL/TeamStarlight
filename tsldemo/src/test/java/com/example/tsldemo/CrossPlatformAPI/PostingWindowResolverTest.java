package com.example.tsldemo.CrossPlatformAPI;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.LocalTime;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The planner writes {@code time_of_day} as free text, so this is the one place a vague
 * campaign slot becomes a real publish moment. Everything it can get wrong publishes at the
 * wrong hour, which is why the odd shapes are pinned rather than assumed.
 */
class PostingWindowResolverTest {

    @Test
    @DisplayName("an explicit 24-hour time is taken as-is")
    void parsesExplicitTime() {
        assertEquals(LocalTime.of(18, 0), PostingWindowResolver.resolve("18:00", "linkedin"));
        assertEquals(LocalTime.of(7, 30), PostingWindowResolver.resolve("07:30", "linkedin"));
        assertEquals(LocalTime.of(9, 5), PostingWindowResolver.resolve("9:05", "facebook"));
    }

    @Test
    @DisplayName("12-hour times with a meridiem convert correctly")
    void parsesMeridiemTime() {
        assertEquals(LocalTime.of(18, 0), PostingWindowResolver.resolve("6pm", "linkedin"));
        assertEquals(LocalTime.of(18, 30), PostingWindowResolver.resolve("6:30 pm", "linkedin"));
        assertEquals(LocalTime.of(9, 0), PostingWindowResolver.resolve("9am", "linkedin"));
        // The inversion hour: 12am is midnight, 12pm is noon.
        assertEquals(LocalTime.of(0, 0), PostingWindowResolver.resolve("12am", "linkedin"));
        assertEquals(LocalTime.of(12, 0), PostingWindowResolver.resolve("12pm", "linkedin"));
    }

    @Test
    @DisplayName("a range resolves to the start of the window")
    void parsesRangeAsItsStart() {
        assertEquals(LocalTime.of(7, 30),
                PostingWindowResolver.resolve("07:30-09:30", "linkedin"));
        assertEquals(LocalTime.of(18, 0),
                PostingWindowResolver.resolve("evenings, 18:00-21:00", "instagram"));
    }

    @Test
    @DisplayName("an explicit time inside prose still wins over the window it names")
    void explicitTimeBeatsNamedWindow() {
        // "morning" would give 08:00 on LinkedIn; the stated time is more specific.
        assertEquals(LocalTime.of(8, 45),
                PostingWindowResolver.resolve("morning (08:45)", "linkedin"));
    }

    @Test
    @DisplayName("a bare number is not treated as a time")
    void ignoresBareNumbers() {
        // The dangerous case: reading "2" as 02:00 would publish in the middle of the night.
        // With no clock shape to latch onto this must fall back to the platform default.
        assertEquals(LocalTime.of(8, 0),
                PostingWindowResolver.resolve("2 posts a week", "linkedin"));
        assertEquals(LocalTime.of(9, 30),
                PostingWindowResolver.resolve("slot 3", "facebook"));
    }

    @Test
    @DisplayName("a real time later in the string is still found after a bare number")
    void keepsScanningPastBareNumbers() {
        assertEquals(LocalTime.of(17, 0),
                PostingWindowResolver.resolve("slot 3, publish at 17:00", "linkedin"));
    }

    @Test
    @DisplayName("an out-of-range number falls through instead of being clamped")
    void ignoresImpossibleTimes() {
        assertEquals(LocalTime.of(8, 0),
                PostingWindowResolver.resolve("99:99", "linkedin"));
    }

    @Test
    @DisplayName("named windows use the platform's own preferred slot")
    void usesPlatformSpecificWindows() {
        // Inside the 07:30–09:30 window skills/posting_plan.md recommends for LinkedIn...
        assertEquals(LocalTime.of(8, 0), PostingWindowResolver.resolve("morning", "linkedin"));
        // ...and the 09:00–11:00 mid-morning one for Facebook. Same word, different platform.
        assertEquals(LocalTime.of(9, 30), PostingWindowResolver.resolve("morning", "facebook"));
        assertEquals(LocalTime.of(19, 0), PostingWindowResolver.resolve("evening", "instagram"));
    }

    @Test
    @DisplayName("a window the platform has no opinion on resolves generically")
    void fallsBackToGenericWindow() {
        // LinkedIn has no documented evening window. Honour the word the planner used rather
        // than substituting an unrelated morning slot.
        assertEquals(LocalTime.of(19, 0), PostingWindowResolver.resolve("evening", "linkedin"));
    }

    @Test
    @DisplayName("window vocabulary is matched, not just exact words")
    void recognisesWindowSynonyms() {
        assertEquals(LocalTime.of(12, 0), PostingWindowResolver.resolve("lunchtime", "linkedin"));
        assertEquals(LocalTime.of(12, 0), PostingWindowResolver.resolve("around noon", "linkedin"));
        assertEquals(LocalTime.of(11, 0),
                PostingWindowResolver.resolve("late morning", "instagram"));
        assertEquals(LocalTime.of(14, 0), PostingWindowResolver.resolve("afternoon", "x"));
    }

    @Test
    @DisplayName("'afternoon' is never mistaken for noon")
    void afternoonIsNotNoon() {
        // "afternoon" contains "noon"; a naive contains() check would collapse the two.
        assertEquals(LocalTime.of(13, 30), PostingWindowResolver.resolve("afternoon", "facebook"));
    }

    @Test
    @DisplayName("blank or missing input falls back to the platform's best slot")
    void fallsBackToPlatformDefault() {
        assertEquals(LocalTime.of(8, 0), PostingWindowResolver.resolve("", "linkedin"));
        assertEquals(LocalTime.of(9, 30), PostingWindowResolver.resolve(null, "facebook"));
        assertEquals(LocalTime.of(19, 0), PostingWindowResolver.resolve("   ", "instagram"));
        assertEquals(LocalTime.of(20, 0), PostingWindowResolver.resolve(null, "tiktok"));
    }

    @Test
    @DisplayName("an unknown platform still resolves rather than failing")
    void handlesUnknownPlatform() {
        assertEquals(LocalTime.of(9, 0), PostingWindowResolver.resolve(null, "snapchat"));
        assertEquals(LocalTime.of(9, 0), PostingWindowResolver.resolve(null, null));
        // A named window still works without a platform table to consult.
        assertEquals(LocalTime.of(19, 0), PostingWindowResolver.resolve("evening", "snapchat"));
    }

    @Test
    @DisplayName("platform aliases fold onto the same table")
    void normalisesPlatformAliases() {
        assertEquals(PostingWindowResolver.resolve("morning", "x"),
                PostingWindowResolver.resolve("morning", "Twitter"));
        assertEquals(PostingWindowResolver.resolve("morning", "facebook"),
                PostingWindowResolver.resolve("morning", "META"));
        assertEquals(LocalTime.of(8, 0), PostingWindowResolver.resolve("morning", "LinkedIn"));
    }

    @Test
    @DisplayName("isExplicit distinguishes the planner's choice from our default")
    void reportsWhetherTheItemNamedATime() {
        assertTrue(PostingWindowResolver.isExplicit("18:00"));
        assertTrue(PostingWindowResolver.isExplicit("morning"));
        assertFalse(PostingWindowResolver.isExplicit(""));
        assertFalse(PostingWindowResolver.isExplicit(null));
        assertFalse(PostingWindowResolver.isExplicit("2 posts a week"));
    }
}
