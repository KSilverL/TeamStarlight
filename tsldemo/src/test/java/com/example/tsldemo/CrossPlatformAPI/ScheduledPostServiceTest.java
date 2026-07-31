package com.example.tsldemo.CrossPlatformAPI;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Instant;
import java.time.ZoneId;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.ScheduledPost;

/**
 * Covers the pure time-resolution and copy-assembly logic, which is where the scheduling bug
 * that motivated this rewrite actually lived: the old code resolved a user's wall-clock time
 * against {@code ZoneId.systemDefault()}, so the same input meant different moments depending
 * on where the JVM ran. These run without Spring or a database.
 */
class ScheduledPostServiceTest {

    private static final ZoneId DUBLIN = ZoneId.of("Europe/Dublin");
    private static final ZoneId UTC = ZoneId.of("UTC");

    @Test
    @DisplayName("a bare wall-clock time is resolved in the zone it was picked in")
    void resolvesWallClockTimeInGivenZone() {
        // July: Ireland is on IST (UTC+1), so 10:00 local is 09:00Z.
        assertEquals(
                Instant.parse("2026-07-18T09:00:00Z"),
                ScheduledPostService.resolveInstant("2026-07-18T10:00:00", DUBLIN));
    }

    @Test
    @DisplayName("the same wall-clock string means a different instant in a different zone")
    void wallClockTimeDependsOnZone() {
        // This one-hour gap is the whole bug: the old code always used the JVM's zone, which is
        // UTC in a container, so a post the user set for 10:00 Irish time went out at 11:00.
        Instant dublin = ScheduledPostService.resolveInstant("2026-07-18T10:00:00", DUBLIN);
        Instant utc = ScheduledPostService.resolveInstant("2026-07-18T10:00:00", UTC);

        assertEquals(Instant.parse("2026-07-18T09:00:00Z"), dublin);
        assertEquals(Instant.parse("2026-07-18T10:00:00Z"), utc);
    }

    @Test
    @DisplayName("daylight saving is applied for the scheduled date, not for today")
    void appliesDaylightSavingOfTheScheduledDate() {
        // January: Ireland is on GMT (UTC+0), so the same 10:00 is 10:00Z — a fixed offset
        // captured at schedule time would get this wrong for half the year.
        assertEquals(
                Instant.parse("2026-01-18T10:00:00Z"),
                ScheduledPostService.resolveInstant("2026-01-18T10:00:00", DUBLIN));
    }

    @Test
    @DisplayName("an offset-qualified time is taken at face value and ignores the zone")
    void offsetQualifiedTimeIgnoresZone() {
        Instant expected = Instant.parse("2026-07-18T09:00:00Z");

        assertEquals(expected,
                ScheduledPostService.resolveInstant("2026-07-18T10:00:00+01:00", DUBLIN));
        // Same input, different fallback zone — the offset in the string wins.
        assertEquals(expected,
                ScheduledPostService.resolveInstant("2026-07-18T10:00:00+01:00", UTC));
    }

    @Test
    @DisplayName("a Z-suffixed instant parses")
    void parsesZuluTime() {
        assertEquals(
                Instant.parse("2026-07-18T10:00:00Z"),
                ScheduledPostService.resolveInstant("2026-07-18T10:00:00Z", DUBLIN));
    }

    @Test
    @DisplayName("surrounding whitespace is tolerated")
    void trimsInput() {
        assertEquals(
                Instant.parse("2026-07-18T09:00:00Z"),
                ScheduledPostService.resolveInstant("  2026-07-18T10:00:00  ", DUBLIN));
    }

    @Test
    @DisplayName("an unparseable time is a 400, not a 500")
    void rejectsMalformedTime() {
        ResponseStatusException e = assertThrows(ResponseStatusException.class,
                () -> ScheduledPostService.resolveInstant("18/07/2026 10:00", DUBLIN));
        assertEquals(HttpStatus.BAD_REQUEST, e.getStatusCode());
    }

    @Test
    @DisplayName("a missing time is a 400, not a NullPointerException")
    void rejectsMissingTime() {
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class,
                        () -> ScheduledPostService.resolveInstant(null, DUBLIN)).getStatusCode());
        assertEquals(HttpStatus.BAD_REQUEST,
                assertThrows(ResponseStatusException.class,
                        () -> ScheduledPostService.resolveInstant("   ", DUBLIN)).getStatusCode());
    }

    @Test
    @DisplayName("hashtags are appended to the body as one block at publish time")
    void appendsHashtagsToPublishedCopy() {
        ScheduledPost post = new ScheduledPost();
        post.setMessage("Bamboo beats plastic.");
        post.setHashtags(new String[] { "#EcoHome", "#BambooKitchen" });

        assertEquals("Bamboo beats plastic.\n\n#EcoHome #BambooKitchen",
                ScheduledPostService.fullText(post));
    }

    @Test
    @DisplayName("copy with no hashtags publishes unchanged")
    void leavesCopyWithoutHashtagsAlone() {
        ScheduledPost post = new ScheduledPost();
        post.setMessage("LinkedIn copy carries no hashtags by convention.");

        // Null (never set) and empty (set to an empty list) must behave identically — LinkedIn
        // posts hit both paths depending on whether the caller sent the field at all.
        assertEquals(post.getMessage(), ScheduledPostService.fullText(post));

        post.setHashtags(new String[0]);
        assertEquals(post.getMessage(), ScheduledPostService.fullText(post));
    }
}
