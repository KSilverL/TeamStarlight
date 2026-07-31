package com.example.tsldemo.CrossPlatformAPI;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import com.example.tsldemo.ENUMS.PlatformEnum;

/**
 * The gate in front of the automatic handoff sweep.
 *
 * <p>Both ways of getting this wrong fail silently. Answer "yes" too readily and every sweep
 * fetches every approved slot's task from the LLM service to be told there is nothing to do;
 * answer "no" too readily and approved posts quietly never reach the calendar, which is the
 * exact failure the sweep exists to prevent. Neither shows up as an error anywhere.
 */
class PlanHandoffNeedsSchedulingTest {

    private static final int BUSINESS_ID = 7;
    private static final String PLAN_ID = "plan-abc";

    /** An approved slot, executed, targeting the given platforms. */
    private static Map<String, Object> item(String... platforms) {
        return Map.of(
                "item_id", "item-1",
                "status", "done",
                "task_id", PLAN_ID + "--item-1",
                "platforms", List.of(platforms));
    }

    /**
     * A repository that reports posts existing for exactly {@code alreadyScheduled}.
     *
     * <p>A proxy rather than a mock because the project has no mocking library on the test
     * classpath, and hand-implementing a Spring Data interface would be pages of unused
     * methods. Anything the service calls that isn't stubbed here fails loudly rather than
     * quietly returning null, so a future change to what it asks the database can't pass by
     * accident.
     */
    private static ScheduledPostRepository repositoryWith(Set<PlatformEnum> alreadyScheduled) {
        return (ScheduledPostRepository) Proxy.newProxyInstance(
                ScheduledPostRepository.class.getClassLoader(),
                new Class<?>[]{ScheduledPostRepository.class},
                (proxy, method, args) -> {
                    if (method.getName().equals(
                            "existsByBusinessIdAndSourcePlanIdAndSourceItemIdAndPlatform")) {
                        return alreadyScheduled.contains((PlatformEnum) args[3]);
                    }
                    throw new UnsupportedOperationException(
                            "needsScheduling should not call " + method.getName());
                });
    }

    /** The service under test, wired to a stub repository. Field injection leaves no seam to
     * construct through, so reflection stands in for the container. */
    private static PlanHandoffService serviceWith(Set<PlatformEnum> alreadyScheduled)
            throws ReflectiveOperationException {
        PlanHandoffService service = new PlanHandoffService();
        Field field = PlanHandoffService.class.getDeclaredField("scheduledPostRepository");
        field.setAccessible(true);
        field.set(service, repositoryWith(alreadyScheduled));
        return service;
    }

    private static boolean needsScheduling(Set<PlatformEnum> alreadyScheduled,
                                           Map<String, Object> item) throws Exception {
        return serviceWith(alreadyScheduled).needsScheduling(BUSINESS_ID, PLAN_ID, item);
    }

    @Test
    @DisplayName("an approved slot with nothing on the calendar is outstanding")
    void approvedAndUnscheduledIsOutstanding() throws Exception {
        assertTrue(needsScheduling(Set.of(), item("linkedin")));
    }

    @Test
    @DisplayName("an approved slot already on the calendar is left alone")
    void approvedAndScheduledIsDone() throws Exception {
        assertFalse(needsScheduling(Set.of(PlatformEnum.LINKEDIN), item("linkedin")));
    }

    @Test
    @DisplayName("a slot half-scheduled across its platforms is still outstanding")
    void partiallyScheduledIsOutstanding() throws Exception {
        // LinkedIn landed; Facebook didn't (no Page connected at the time). Connecting the Page
        // should let the sweep finish the job rather than leaving the slot permanently half-done.
        assertTrue(needsScheduling(Set.of(PlatformEnum.LINKEDIN), item("linkedin", "facebook")));
    }

    @Test
    @DisplayName("a slot targeting only platforms we cannot publish to is not outstanding")
    void unpublishablePlatformsAreNotOutstanding() throws Exception {
        // Instagram has no publishing path. Treating it as outstanding would make this slot
        // fetch its task on every single sweep, forever, to be told the same thing.
        assertFalse(needsScheduling(Set.of(), item("instagram", "tiktok")));
    }

    @Test
    @DisplayName("a slot still awaiting review is not touched")
    void unapprovedIsNotOutstanding() throws Exception {
        assertFalse(needsScheduling(Set.of(), Map.of(
                "item_id", "item-1",
                "status", "awaiting_review",
                "task_id", PLAN_ID + "--item-1",
                "platforms", List.of("linkedin"))));
    }

    @Test
    @DisplayName("a slot marked done but never executed is not touched")
    void doneWithoutATaskIsNotOutstanding() throws Exception {
        // No task means no copy to read, so there is nothing this could schedule.
        Map<String, Object> item = new java.util.HashMap<>();
        item.put("item_id", "item-1");
        item.put("status", "done");
        item.put("task_id", null);
        item.put("platforms", List.of("linkedin"));

        assertFalse(needsScheduling(Set.of(), item));
    }

    @Test
    @DisplayName("a cancelled post counts as handled, so the sweep won't re-create it")
    void cancelledPostIsNotResurrected() throws Exception {
        // The narrower guard inside the handoff ignores cancelled posts on purpose, so that
        // re-running it by hand works. The sweep must not use that rule: cancelling a post on
        // the calendar would otherwise be undone automatically a couple of minutes later.
        Set<PlatformEnum> anyStatusRowExists = Set.of(PlatformEnum.LINKEDIN);

        assertFalse(needsScheduling(anyStatusRowExists, item("linkedin")));
    }

    @Test
    @DisplayName("platform aliases resolve the same way the handoff resolves them")
    void mapsPlatformAliases() throws Exception {
        // The plan may say "meta" or "facebook" for the same connection. If this disagreed with
        // the handoff's own mapping, the sweep would keep finding work the handoff then skips.
        assertFalse(needsScheduling(Set.of(PlatformEnum.META), item("meta")));
        assertFalse(needsScheduling(Set.of(PlatformEnum.META), item("facebook")));
    }

    @Test
    @DisplayName("every platform on a slot is checked, not just the first")
    void checksEveryPlatform() throws Exception {
        List<PlatformEnum> asked = new ArrayList<>();
        PlanHandoffService service = new PlanHandoffService();
        Field field = PlanHandoffService.class.getDeclaredField("scheduledPostRepository");
        field.setAccessible(true);
        field.set(service, Proxy.newProxyInstance(
                ScheduledPostRepository.class.getClassLoader(),
                new Class<?>[]{ScheduledPostRepository.class},
                (proxy, method, args) -> {
                    asked.add((PlatformEnum) args[3]);
                    return true;  // everything already scheduled — forces a full walk
                }));

        assertFalse(service.needsScheduling(BUSINESS_ID, PLAN_ID, item("linkedin", "facebook")));
        assertTrue(new HashSet<>(asked).containsAll(
                List.of(PlatformEnum.LINKEDIN, PlatformEnum.META)));
    }
}
