package com.example.tsldemo.CrossPlatformAPI;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import com.example.tsldemo.CrossPlatformAPI.PlanHandoffService.ScheduleOptions;
import com.example.tsldemo.CrossPlatformAPI.PlanHandoffService.SkippedPlatform;

/**
 * What happens when a slot's posting window has already gone.
 *
 * <p>This used to be a dead end. The copy was written and approved, the clock had simply moved
 * past it, and the handoff dropped the post with "that time has already passed" — leaving the
 * user nothing but the button that had just failed. The rules worth pinning are that nothing
 * moves on its own, and that when the caller does ask for a new time, the slot's own window
 * survives.
 */
class PlanHandoffRescheduleTest {

    /** Reaches `resolvePublishMoment`, which is private because nothing outside the handoff has
     * any business computing a publish time — but it is where every one of these rules lives. */
    private static Object resolve(
            PlanHandoffService service, LocalDate date, String timeOfDay,
            String platform, ScheduleOptions options) throws Exception {
        Method method = PlanHandoffService.class.getDeclaredMethod(
                "resolvePublishMoment", LocalDate.class, String.class, String.class,
                ScheduleOptions.class);
        method.setAccessible(true);
        try {
            return method.invoke(service, date, timeOfDay, platform, options);
        } catch (InvocationTargetException e) {
            throw (Exception) e.getCause();  // unwrap so tests assert on the real exception
        }
    }

    /** The handoff only needs its zone for this, and `defaultZone` is the one thing it asks. */
    private static PlanHandoffService service() throws ReflectiveOperationException {
        PlanHandoffService handoff = new PlanHandoffService();
        ScheduledPostService posts = new ScheduledPostService();

        var zoneField = ScheduledPostService.class.getDeclaredField("defaultTimezone");
        zoneField.setAccessible(true);
        zoneField.set(posts, "Europe/Dublin");

        var field = PlanHandoffService.class.getDeclaredField("scheduledPostService");
        field.setAccessible(true);
        field.set(handoff, posts);
        return handoff;
    }

    private static LocalDate today() {
        return LocalDate.now(ZoneId.of("Europe/Dublin"));
    }

    @Test
    @DisplayName("a slot still ahead is scheduled exactly as planned")
    void keepsAFutureSlotUntouched() throws Exception {
        LocalDate future = today().plusDays(3);

        Object when = resolve(service(), future, "morning", "linkedin",
                ScheduleOptions.forPages(List.of()));

        assertEquals(future.atTime(8, 0), when);  // LinkedIn's morning window
    }

    @Test
    @DisplayName("a passed slot is refused rather than quietly moved")
    void refusesAPassedSlotByDefault() throws Exception {
        // The default has to be "nothing happens". A post appearing on a different day than the
        // plan shows is worse than one that visibly didn't go out, because nobody goes looking.
        LocalDate past = today().minusDays(2);

        SkippedPlatform skip = assertThrows(SkippedPlatform.class, () ->
                resolve(service(), past, "morning", "linkedin",
                        ScheduleOptions.forPages(List.of())));

        assertEquals("time_passed", skip.code());
        assertTrue(skip.getMessage().contains(past.toString()));
    }

    @Test
    @DisplayName("auto-reschedule keeps the slot's window and only moves the day")
    void autoRescheduleKeepsTheWindow() throws Exception {
        LocalDate past = today().minusDays(5);

        Object when = resolve(service(), past, "morning", "linkedin",
                new ScheduleOptions(List.of(), null, true));

        // 08:00 on some day at or after today — the morning post stays a morning post rather
        // than going out at whatever hour the approval happened to land on.
        assertEquals(java.time.LocalTime.of(8, 0), ((java.time.LocalDateTime) when).toLocalTime());
        assertTrue(((java.time.LocalDateTime) when).toLocalDate().compareTo(today()) >= 0);
    }

    @Test
    @DisplayName("auto-reschedule respects each platform's own window")
    void autoReschedulePerPlatform() throws Exception {
        LocalDate past = today().minusDays(5);
        var options = new ScheduleOptions(List.of(), null, true);

        Object linkedin = resolve(service(), past, "morning", "linkedin", options);
        Object instagram = resolve(service(), past, "evening", "instagram", options);

        assertEquals(java.time.LocalTime.of(8, 0), ((java.time.LocalDateTime) linkedin).toLocalTime());
        assertEquals(java.time.LocalTime.of(19, 0), ((java.time.LocalDateTime) instagram).toLocalTime());
    }

    @Test
    @DisplayName("an explicit time from the user wins over the slot's own")
    void explicitTimeWins() throws Exception {
        LocalDate past = today().minusDays(2);
        String chosen = today().plusDays(1).atTime(14, 30).toString();

        Object when = resolve(service(), past, "morning", "linkedin",
                new ScheduleOptions(List.of(), chosen, false));

        assertEquals(today().plusDays(1).atTime(14, 30), when);
    }

    @Test
    @DisplayName("an explicit time in the past is refused, not silently rolled forward")
    void explicitTimeMustBeFuture() throws Exception {
        String stale = today().minusDays(1).atTime(9, 0).toString();

        SkippedPlatform skip = assertThrows(SkippedPlatform.class, () ->
                resolve(service(), today(), "morning", "linkedin",
                        new ScheduleOptions(List.of(), stale, false)));

        assertEquals("time_passed", skip.code());
    }

    @Test
    @DisplayName("an unreadable time is reported rather than falling back to the planned one")
    void rejectsAnUnparseableTime() throws Exception {
        // Falling back would schedule a post at a time the user did not choose and was never
        // shown — the request said "put it here", so failing loudly is the honest answer.
        SkippedPlatform skip = assertThrows(SkippedPlatform.class, () ->
                resolve(service(), today().plusDays(1), "morning", "linkedin",
                        new ScheduleOptions(List.of(), "next tuesday-ish", false)));

        assertEquals("error", skip.code());
    }
}
