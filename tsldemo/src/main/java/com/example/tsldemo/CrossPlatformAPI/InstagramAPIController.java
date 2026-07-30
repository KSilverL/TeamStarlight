package com.example.tsldemo.CrossPlatformAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.DTOs.Request.InstagramVideoPostReqDTO;
import com.example.tsldemo.auth.JwtUtil;

@RestController
@RequestMapping("/instagram")
public class InstagramAPIController {

    private final InstagramAPIService instagramAPIService;
    private final InstagramPublishJobStore jobStore;
    private final JwtUtil jwtUtil;

    public InstagramAPIController(InstagramAPIService instagramAPIService,
                                  InstagramPublishJobStore jobStore,
                                  JwtUtil jwtUtil) {
        this.instagramAPIService = instagramAPIService;
        this.jobStore = jobStore;
        this.jwtUtil = jwtUtil;
    }

    /** The business is taken from the JWT, never from the request body, so one business cannot
     * publish through another's Instagram connection. Mirrors CrossPlatformController's own
     * requireBusinessId — this endpoint previously had no authentication at all. */
    private int requireBusinessId(String authHeader) {
        int businessId = jwtUtil.extractBusinessId(authHeader);
        if (businessId == -1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Missing or invalid authorization token");
        }
        return businessId;
    }

    /** Starts a publish and returns immediately with a job to poll.
     *
     * 202 rather than 200: the post has been accepted, not completed. Instagram transcodes
     * asynchronously and can take minutes, which is longer than the browser will hold a request
     * open — and a client-side timeout on a synchronous publish looks like a failure even when the
     * post succeeds, inviting a retry that posts twice.
     *
     * Credential and permission problems are still resolved synchronously inside the service, so
     * they come back in THIS response rather than only in a later poll. */
    @PostMapping("/post-video")
    public ResponseEntity<?> postVideo(
            @RequestBody InstagramVideoPostReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);

        if (requestDTO.jobId() == null || requestDTO.jobId().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "jobId is required");
        }

        InstagramPublishJob job = instagramAPIService.startPostVideo(
                businessId, requestDTO.pageIds(), requestDTO.jobId(), requestDTO.caption());

        return ResponseEntity.accepted().body(statusBody(job));
    }

    /** Status of a publish started by this business. */
    @GetMapping("/post-video/{publishJobId}")
    public ResponseEntity<?> postVideoStatus(
            @PathVariable String publishJobId,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        return ResponseEntity.ok(statusBody(jobStore.requireOwned(publishJobId, businessId)));
    }

    /** Lower-cased status so it reads the same as the video render jobs the frontend already
     * polls ("pending" / "done" / "error"), rather than making the client learn a second vocabulary
     * for the same idea. HashMap because Map.of rejects null values and `error` is normally null. */
    private Map<String, Object> statusBody(InstagramPublishJob job) {
        Map<String, Object> body = new HashMap<>();
        body.put("publishJobId", job.getId());
        body.put("status", job.getStatus().name().toLowerCase());
        body.put("stage", job.getStage());
        body.put("mediaIds", job.getMediaIds());
        body.put("error", job.getError());
        return body;
    }
}
