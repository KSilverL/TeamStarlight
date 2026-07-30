package com.example.tsldemo.CrossPlatformAPI;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.auth.JwtUtil;

@RestController
@RequestMapping("/plans")
public class PlanController {

    private final PlanService planService;
    private final JwtUtil jwtUtil;

    public PlanController(PlanService planService, JwtUtil jwtUtil) {
        this.planService = planService;
        this.jwtUtil = jwtUtil;
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

    @PostMapping("/{planId}/confirm")
    public ResponseEntity<?> confirmPlan(
            @PathVariable String planId,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        int businessId = requireBusinessId(authHeader);
        requireOwnedPlan(planId, businessId); // 403s before we let the confirm through
        return ResponseEntity.ok(planService.confirmPlan(planId));
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

//    @PostMapping("/{planId}/items/{itemId}/execute")
//    public ResponseEntity<?> executePlanItem(
//            @PathVariable String planId,
//            @PathVariable String itemId,
//            @RequestBody(required = false) Map<String, Object> body,
//            @RequestHeader(value = "Authorization", required = false) String authHeader) {
//        int businessId = requireBusinessId(authHeader);
//        requireOwnedPlan(planId, businessId);
//        return ResponseEntity.ok(planService.executePlanItem(planId, itemId, body));
//    }
   
    
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

}