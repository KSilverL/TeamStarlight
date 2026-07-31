package com.example.tsldemo.CrossPlatformAPI;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import com.example.tsldemo.ScheduledPost;

/**
 * The hashtag split decides what actually gets published, because the body and the tags are
 * stored apart and re-joined at publish time. A wrong split changes the post.
 */
class PlanHandoffServiceTest {

    /** What publishing will actually send, so a test can assert on the round trip rather than
     * on the split alone. */
    private static String published(String message, List<String> hashtags) {
        ScheduledPost post = new ScheduledPost();
        post.setMessage(message);
        post.setHashtags(hashtags.toArray(String[]::new));
        return ScheduledPostService.fullText(post);
    }

    @Test
    @DisplayName("a trailing hashtag line is split off the body")
    void splitsTrailingHashtagLine() {
        var copy = PlanHandoffService.splitHashtags(
                "Bamboo beats plastic.\n\n#EcoHome #BambooKitchen");

        assertEquals("Bamboo beats plastic.", copy.message());
        assertEquals(List.of("#EcoHome", "#BambooKitchen"), copy.hashtags());
    }

    @Test
    @DisplayName("a draft that already ends in a hashtag line publishes unchanged")
    void roundTripsFaithfully() {
        String original = "Bamboo beats plastic.\n\n#EcoHome #BambooKitchen";
        var copy = PlanHandoffService.splitHashtags(original);

        assertEquals(original, published(copy.message(), copy.hashtags()));
    }

    @Test
    @DisplayName("hashtags spread over several lines collapse onto one")
    void collapsesMultipleHashtagLines() {
        var copy = PlanHandoffService.splitHashtags(
                "Body copy here.\n\n#One #Two\n#Three");

        assertEquals("Body copy here.", copy.message());
        assertEquals(List.of("#One", "#Two", "#Three"), copy.hashtags());
        assertEquals("Body copy here.\n\n#One #Two #Three",
                published(copy.message(), copy.hashtags()));
    }

    @Test
    @DisplayName("a hashtag inside a sentence stays in the body")
    void leavesInlineHashtagsAlone() {
        // The line has non-hashtag tokens, so it is prose — not a tag block.
        var copy = PlanHandoffService.splitHashtags(
                "We hit #1 in sustainable homewares this month.");

        assertEquals("We hit #1 in sustainable homewares this month.", copy.message());
        assertTrue(copy.hashtags().isEmpty());
    }

    @Test
    @DisplayName("a body ending in a hashtag sentence is not mistaken for a tag block")
    void doesNotStripASentenceEndingInAHashtag() {
        var copy = PlanHandoffService.splitHashtags(
                "Tell us what you think #EcoHome\n\n#Sustainability");

        // Only the genuine trailing block moves; the sentence keeps its inline tag.
        assertEquals("Tell us what you think #EcoHome", copy.message());
        assertEquals(List.of("#Sustainability"), copy.hashtags());
    }

    @Test
    @DisplayName("copy with no hashtags is left entirely alone")
    void handlesCopyWithoutHashtags() {
        String original = "LinkedIn copy carries no hashtags by convention.";
        var copy = PlanHandoffService.splitHashtags(original);

        assertEquals(original, copy.message());
        assertTrue(copy.hashtags().isEmpty());
        assertEquals(original, published(copy.message(), copy.hashtags()));
    }

    @Test
    @DisplayName("a repeated tag is only published once")
    void deduplicatesHashtags() {
        var copy = PlanHandoffService.splitHashtags(
                "Body.\n\n#EcoHome #BambooKitchen\n#EcoHome");

        assertEquals(List.of("#EcoHome", "#BambooKitchen"), copy.hashtags());
    }

    @Test
    @DisplayName("a draft that is nothing but hashtags leaves an empty body")
    void handlesHashtagOnlyDraft() {
        var copy = PlanHandoffService.splitHashtags("#EcoHome #BambooKitchen");

        assertEquals("", copy.message());
        assertEquals(List.of("#EcoHome", "#BambooKitchen"), copy.hashtags());
    }

    @Test
    @DisplayName("trailing whitespace and blank lines don't leak into the body")
    void trimsTrailingWhitespace() {
        var copy = PlanHandoffService.splitHashtags(
                "Body copy.\n\n\n#Tag\n\n   \n");

        assertEquals("Body copy.", copy.message());
        assertEquals(List.of("#Tag"), copy.hashtags());
    }

    @Test
    @DisplayName("a bare '#' is not a hashtag")
    void ignoresBareHashSymbol() {
        // "#" alone fails the length check, so the line reads as prose and stays put.
        var copy = PlanHandoffService.splitHashtags("Body copy.\n\n#");

        assertEquals("Body copy.\n\n#", copy.message());
        assertTrue(copy.hashtags().isEmpty());
    }

    /**
     * Rolling a missed slot forward.
     *
     * <p>A slot whose time has gone used to be a dead end — dropped with "that time has already
     * passed" and no way to recover it but re-approving something that would fail again. The
     * rule that matters is which part moves: the day, never the window.
     */
    @Nested
    @DisplayName("next viable slot")
    class NextViableSlot {

        /** 15 minutes past 09:00 on the 3rd — the earliest a post could now be scheduled. */
        private static final LocalDateTime EARLIEST = LocalDateTime.parse("2026-08-03T09:15");

        @Test
        @DisplayName("a window still ahead today keeps today's date")
        void staysTodayWhenTheWindowIsAhead() {
            // Approved at 09:15 for an evening slot — it can still go out tonight, and moving
            // it to tomorrow would delay a post that was perfectly publishable.
            assertEquals(
                    LocalDateTime.parse("2026-08-03T19:00"),
                    PlanHandoffService.nextViableSlot(LocalTime.of(19, 0), EARLIEST));
        }

        @Test
        @DisplayName("a window already gone today moves to tomorrow, same time")
        void movesToTomorrowKeepingTheWindow() {
            // The whole point: a morning post stays a morning post. Publishing it at 09:15
            // because that is when someone happened to approve it defeats the plan.
            assertEquals(
                    LocalDateTime.parse("2026-08-04T08:00"),
                    PlanHandoffService.nextViableSlot(LocalTime.of(8, 0), EARLIEST));
        }

        @Test
        @DisplayName("a slot missed weeks ago lands on the next occurrence, not a walk forward")
        void jumpsStraightToTheNextOccurrence() {
            // Computed from today rather than stepping day-by-day from the original date, so an
            // ancient slot costs one comparison instead of a loop over every day since.
            assertEquals(
                    LocalDateTime.parse("2026-08-04T08:00"),
                    PlanHandoffService.nextViableSlot(LocalTime.of(8, 0), EARLIEST));
        }

        @Test
        @DisplayName("a window exactly at the earliest moment is still usable")
        void acceptsTheBoundary() {
            // isBefore, not isAfter — the lead already contains the safety margin, so a slot
            // landing exactly on it does not need pushing another day out.
            assertEquals(
                    LocalDateTime.parse("2026-08-03T09:15"),
                    PlanHandoffService.nextViableSlot(LocalTime.of(9, 15), EARLIEST));
        }
    }
}
