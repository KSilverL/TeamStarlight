package com.example.tsldemo.CrossPlatformAPI;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.AgentAPI.TaskAccess;
import com.example.tsldemo.auth.JwtUtil;

@RestController
@RequestMapping("/plans")
public class PlanController {

    private final PlanService planService;
    private final PlanHandoffService planHandoffService;
    private final PlanCampaignDrafter planCampaignDrafter;
    private final JwtUtil jwtUtil;
    private final TaskAccess taskAccess;

    public PlanController(PlanService planService,
                          PlanHandoffService planHandoffService,
                          PlanCampaignDrafter planCampaignDrafter,
                          JwtUtil jwtUtil,
                          TaskAccess taskAccess) {
        this.planService = planService;
        this.planHandoffService = planHandoffService;
        this.planCampaignDrafter = planCampaignDrafter;
        this.jwtUtil = jwtUtil;
        this.taskAccess = taskAccess;
    }

    private int requireBusinessId(String authHeader) {
        int businessId = jwtUtil.extractBusinessId(authHeader);
        if (businessId == -1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Missing or invalid authorization token");
        }
        return businessId;
    }

    /**
     * Fetches the plan and verifies it belongs to the calling business before
     * returning it. Throws 403 if the plan belongs to someone else, 404 if the
     * LLM service reports the plan doesn't exist (bubbles up from getPlan()).
     */
    private Map<String, Object> requireOwnedPlan(String planId, int businessId) {
        Map<String, Object> plan = planService.getPlan(planId);

        Object ownerId = plan.get("business_id");
        if (ownerId == null || !String.valueOf(businessId).equals(String.valueOf(ownerId))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "You don't have access to this plan.");
        }

        return plan;
    }

    @PostMapping
    public ResponseEntity<?> createPlan(
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        return ResponseEntity.ok(planService.createPlan(businessId, body));
    }

    @GetMapping
    public ResponseEntity<?> listPlans(
            @RequestParam(value = "status", required = false) String status,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        return ResponseEntity.ok(planService.listPlans(businessId, status));
    }

    @GetMapping("/{planId}")
    public ResponseEntity<?> getPlan(
            @PathVariable String planId,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        Map<String, Object> plan = requireOwnedPlan(planId, businessId);
        return ResponseEntity.ok(plan);
    }

    /**
     * Activates a plan and starts writing its posts.
     *
     * <p>Confirming a campaign means committing to it, so every slot is drafted now rather than
     * a day before its own date — the user gets the whole campaign to review as one body of
     * work. Each draft still stops at the human gate; this changes when the copy is written,
     * not who signs it off.
     *
     * <p>The drafting runs in the background and this returns as soon as the plan is active:
     * writing a campaign is minutes of model work, and there is nothing to show the caller
     * until the first draft lands anyway. The response's items therefore still read
     * {@code planned} — they move to {@code generating} over the following seconds.
     */
    @PostMapping("/{planId}/confirm")
    public ResponseEntity<?> confirmPlan(
            @PathVariable String planId,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        requireOwnedPlan(planId, businessId); // 403s before we let the confirm through

        Map<String, Object> confirmed = planService.confirmPlan(planId);
        planCampaignDrafter.draftAll(planId);

        return ResponseEntity.ok(confirmed);
    }

    @PatchMapping("/{planId}/items/{itemId}")
    public ResponseEntity<?> patchPlanItem(
            @PathVariable String planId,
            @PathVariable String itemId,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        requireOwnedPlan(planId, businessId);
        return ResponseEntity.ok(planService.patchPlanItem(planId, itemId, body));
    }

    /**
     * Drafts one plan slot on demand, rather than waiting for the nightly job to reach it.
     *
     * <p>The daily {@link PlanScheduler} bypasses this controller and calls the service
     * directly, so the automated path kept working while this endpoint was commented out —
     * only the frontend's "run this slot now" button was hitting a 404.
     */
    @PostMapping("/{planId}/items/{itemId}/execute")
    public ResponseEntity<?> executePlanItem(
            @PathVariable String planId,
            @PathVariable String itemId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        requireOwnedPlan(planId, businessId);
        Map<String, Object> result = planService.executePlanItem(planId, itemId, body);
        // A plan slot spawns an ordinary newsroom run, so claim it for this business the same way
        // POST /tasks does. Without this the run would be unowned and readable by anyone holding
        // its id — the same hole, reached through a different door.
        if (result != null && result.get("task_id") != null) {
            taskAccess.remember(String.valueOf(result.get("task_id")), authHeader);
        }
        return ResponseEntity.ok(result);
    }


    /**
     * Schedules the approved copy for one plan slot.
     *
     * <p>Called straight after a successful approve, because the LLM service keeps task outputs
     * in memory — the copy has to be captured into the database while it is still there, not
     * collected on some later pass.
     *
     * <p>Answers 200 with a per-platform breakdown even when nothing could be scheduled: one
     * slot can target platforms with no publishing integration, and the caller needs to see
     * which of them landed rather than a single pass/fail for the lot.
     */
    @PostMapping("/{planId}/items/{itemId}/schedule")
    public ResponseEntity<?> scheduleApprovedItem(
            @PathVariable String planId,
            @PathVariable String itemId,
            @RequestBody(required = false) Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        Map<String, Object> plan = requireOwnedPlan(planId, businessId);

        // A slot whose time has passed can't be scheduled as planned. `scheduled_at` is the
        // user picking a new moment; `auto_reschedule` is them asking us to pick the next one
        // in the slot's own window. Neither is assumed — without one, a passed slot is
        // reported as skipped rather than quietly moved to another day.
        PlanHandoffService.ScheduleOptions options = new PlanHandoffService.ScheduleOptions(
                pageIdsFrom(body),
                body == null ? null : asText(body.get("scheduled_at")),
                body != null && Boolean.parseBoolean(String.valueOf(body.get("auto_reschedule"))));

        return ResponseEntity.ok(
                planHandoffService.scheduleApprovedItem(businessId, plan, itemId, options));
    }

    private static String asText(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    /**
     * What this plan's slots have actually put on the calendar, keyed by item id.
     *
     * <p>The plan view can otherwise only report that a slot was approved, which says nothing
     * about whether anything was queued to publish. Reading the scheduled posts back lets it
     * show the real publish times, and offer to schedule the slots that have none.
     */
    @GetMapping("/{planId}/scheduled")
    public ResponseEntity<?> listScheduledForPlan(
            @PathVariable String planId,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        requireOwnedPlan(planId, businessId);

        return ResponseEntity.ok(Map.of(
                "plan_id", planId,
                "items", planHandoffService.listScheduledByItem(businessId, planId)));
    }

    /** Reads the browser's chosen Facebook Pages out of the request body. Absent or malformed
     * means "use whatever the connection has" — the handoff falls back rather than failing. */
    private static List<Long> pageIdsFrom(Map<String, Object> body) {
        if (body == null || !(body.get("page_ids") instanceof List<?> raw)) {
            return List.of();
        }
        List<Long> pageIds = new ArrayList<>();
        for (Object value : raw) {
            try {
                pageIds.add(Long.parseLong(String.valueOf(value)));
            } catch (NumberFormatException e) {
                // Skip the bad entry; a mistyped id must not block the Pages that are valid.
            }
        }
        return pageIds;
    }

    @GetMapping("/tasks/{taskId}")
    public ResponseEntity<?> getTask(
            @PathVariable String taskId
    ){
        return ResponseEntity.ok(
            planService.getTask(taskId)
        );
    }
    
    @PostMapping("/clarify")
    public ResponseEntity<?> clarifyPlan(
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        return ResponseEntity.ok(planService.clarifyPlan(businessId, body));
    }
    
    @PostMapping("/{planId}/refine")
    public ResponseEntity<?> refinePlan(
            @PathVariable String planId,
            @RequestBody Map<String,Object> body,
            @RequestHeader(value="Authorization", required=false)
            String authHeader) {

        int businessId = requireBusinessId(authHeader);

        requireOwnedPlan(planId, businessId);

        return ResponseEntity.ok(
                planService.refinePlan(planId, body)
        );
    }

    /**
     * Spring Boot 4 drops a ResponseStatusException's reason from the default error body, so
     * without this the handoff's conflicts ("approve it first", "still generating") and the
     * ownership 403 would all reach the browser as bare status text. The reason is the whole
     * message — it names what the user has to do next — so relay it in a body the frontend can
     * show verbatim.
     */
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<?> handleStatusException(ResponseStatusException e) {
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.of("error", e.getReason() == null ? "Request failed." : e.getReason()));
    }
}