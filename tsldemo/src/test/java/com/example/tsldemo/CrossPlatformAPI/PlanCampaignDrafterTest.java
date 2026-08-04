package com.example.tsldemo.CrossPlatformAPI;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Which slots a confirmed campaign actually starts writing.
 *
 * <p>The failure this guards against is quiet and expensive: a campaign that stops drafting
 * part-way leaves the user with a plan that looks confirmed and a handful of posts that never
 * appear, and nothing in the UI distinguishes that from "still working".
 */
class PlanCampaignDrafterTest {

    /** Records which items were asked to draft, and can be told to fail on specific ones. */
    private static class RecordingPlanService extends PlanService {
        private final Map<String, Object> plan;
        private final List<String> failOn;
        final List<String> executed = new ArrayList<>();

        RecordingPlanService(Map<String, Object> plan, List<String> failOn) {
            super(null);  // the RestClient is never touched — both calls are overridden
            this.plan = plan;
            this.failOn = failOn;
        }

        @Override
        public Map<String, Object> getPlan(String planId) {
            return plan;
        }

        @Override
        public Map<String, Object> executePlanItem(String planId, String itemId, Map<String, Object> body) {
            if (failOn.contains(itemId)) {
                // What a 409 from the LLM service looks like by the time it reaches here: the
                // slot was already started by the backstop job or a "Generate Draft Now" click.
                throw new IllegalStateException("409 item " + itemId + " is not executable");
            }
            executed.add(itemId);
            return Map.of("task", Map.of("task_id", planId + "--" + itemId));
        }
    }

    private static Map<String, Object> item(String itemId, String status) {
        return Map.of("item_id", itemId, "status", status, "platforms", List.of("linkedin"));
    }

    private static Map<String, Object> planWith(Map<String, Object>... items) {
        return Map.of("plan_id", "plan-abc", "status", "active", "items", List.of(items));
    }

    /**
     * Runs the drafter's work synchronously, with no stagger.
     *
     * <p>Calls the private worker directly rather than {@code draftAll}, so the test asserts on
     * a finished run instead of racing a background thread.
     */
    private static RecordingPlanService drive(Map<String, Object> plan, List<String> failOn)
            throws ReflectiveOperationException {
        PlanCampaignDrafter drafter = new PlanCampaignDrafter();
        RecordingPlanService planService = new RecordingPlanService(plan, failOn);

        Field serviceField = PlanCampaignDrafter.class.getDeclaredField("planService");
        serviceField.setAccessible(true);
        serviceField.set(drafter, planService);

        Field staggerField = PlanCampaignDrafter.class.getDeclaredField("staggerMs");
        staggerField.setAccessible(true);
        staggerField.set(drafter, 0L);

        Method draft = PlanCampaignDrafter.class.getDeclaredMethod("draft", String.class);
        draft.setAccessible(true);
        draft.invoke(drafter, "plan-abc");

        return planService;
    }

    @Test
    @DisplayName("every planned slot in the campaign is started")
    void draftsTheWholeCampaign() throws Exception {
        var planService = drive(planWith(
                item("item-1", "planned"),
                item("item-2", "planned"),
                item("item-3", "planned")), List.of());

        assertEquals(List.of("item-1", "item-2", "item-3"), planService.executed);
    }

    @Test
    @DisplayName("slots that are already under way or settled are left alone")
    void skipsSlotsThatAreNotPlanned() throws Exception {
        // Re-drafting these would either 409 or, worse, replace copy the user already approved.
        var planService = drive(planWith(
                item("item-1", "planned"),
                item("item-2", "generating"),
                item("item-3", "awaiting_review"),
                item("item-4", "done"),
                item("item-5", "skipped")), List.of());

        assertEquals(List.of("item-1"), planService.executed);
    }

    @Test
    @DisplayName("one slot failing does not stop the rest of the campaign")
    void carriesOnAfterAFailedSlot() throws Exception {
        var planService = drive(planWith(
                item("item-1", "planned"),
                item("item-2", "planned"),
                item("item-3", "planned")), List.of("item-2"));

        assertEquals(List.of("item-1", "item-3"), planService.executed);
    }

    @Test
    @DisplayName("a plan with nothing left to draft is a no-op")
    void handlesAFullyDraftedPlan() throws Exception {
        var planService = drive(planWith(
                item("item-1", "done"),
                item("item-2", "skipped")), List.of());

        assertTrue(planService.executed.isEmpty());
    }
}
