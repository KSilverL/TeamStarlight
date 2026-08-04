package com.example.tsldemo.CrossPlatformAPI;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.ScheduledPost;
import com.example.tsldemo.DTOs.Request.ScheduledPostPatchDTO;
import com.example.tsldemo.DTOs.Request.ScheduledPostReqDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.ScheduledPostRespDTO;
import com.example.tsldemo.auth.JwtUtil;

/**
 * The content calendar's CRUD surface.
 *
 * <p>Every endpoint is scoped to the business in the JWT and never to anything the caller
 * supplies, so one business can't read, edit or cancel another's schedule.
 */
@RestController
@RequestMapping("/schedule/posts")
public class ScheduledPostController {

    private final ScheduledPostService scheduledPostService;
    private final JwtUtil jwtUtil;

    public ScheduledPostController(ScheduledPostService scheduledPostService, JwtUtil jwtUtil) {
        this.scheduledPostService = scheduledPostService;
        this.jwtUtil = jwtUtil;
    }

    private int requireBusinessId(String authHeader) {
        int businessId = jwtUtil.extractBusinessId(authHeader);
        if (businessId == -1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                    "Missing or invalid authorization token");
        }
        return businessId;
    }

    /** Lists the schedule, optionally bounded to a date range.
     *
     * <p>{@code from}/{@code to} are plain ISO dates because that is what a month grid asks
     * for; they are widened to cover the whole of both days in the caller's timezone so a post
     * at 23:30 on the last day of the range isn't dropped by an off-by-one on the boundary. */
    @GetMapping
    public ResponseEntity<?> list(
            @RequestParam(value = "from", required = false) String from,
            @RequestParam(value = "to", required = false) String to,
            @RequestParam(value = "timezone", required = false) String timezone,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);

        ZoneId zone;
        Instant fromInstant;
        Instant toInstant;
        try {
            zone = timezone == null || timezone.isBlank()
                    ? scheduledPostService.defaultZone()
                    : ZoneId.of(timezone);
            fromInstant = from == null || from.isBlank() ? null
                    : LocalDate.parse(from).atStartOfDay(zone).toInstant();
            toInstant = to == null || to.isBlank() ? null
                    : LocalDate.parse(to).atTime(LocalTime.MAX).atZone(zone).toInstant();
        } catch (DateTimeException e) {
            // A malformed query string is the caller's mistake, not a server fault — say which
            // part is wrong rather than letting it surface as a 500.
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "from/to must be ISO dates (\"2026-06-01\") and timezone an IANA name "
                    + "(\"Europe/Dublin\").");
        }

        List<ScheduledPost> posts = scheduledPostService.list(businessId, fromInstant, toInstant);
        List<ScheduledPostRespDTO> body = posts.stream()
                .map(post -> ScheduledPostRespDTO.from(post, scheduledPostService.defaultZone()))
                .toList();

        return ResponseEntity.ok(Map.of("posts", body, "total", body.size()));
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> get(
            @PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        ScheduledPost post = scheduledPostService.get(businessId, id);
        return ResponseEntity.ok(ScheduledPostRespDTO.from(post, scheduledPostService.defaultZone()));
    }

    @PostMapping
    public ResponseEntity<?> create(
            @RequestBody ScheduledPostReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        ScheduledPost post = scheduledPostService.create(businessId, requestDTO);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ScheduledPostRespDTO.from(post, scheduledPostService.defaultZone()));
    }

    @PatchMapping("/{id}")
    public ResponseEntity<?> update(
            @PathVariable long id,
            @RequestBody ScheduledPostPatchDTO patch,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        ScheduledPost post = scheduledPostService.update(businessId, id, patch);
        return ResponseEntity.ok(ScheduledPostRespDTO.from(post, scheduledPostService.defaultZone()));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<?> cancel(
            @PathVariable long id,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        scheduledPostService.cancel(businessId, id);
        return ResponseEntity.noContent().build();
    }

    /**
     * Spring Boot 4 drops a ResponseStatusException's reason from the default error body, so
     * without this every validation failure here would reach the browser as a bare "Bad
     * Request". The reason is the entire point — it names the time, Page or platform the user
     * has to fix — so return it in a body the frontend can relay verbatim.
     */
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<?> handleStatusException(ResponseStatusException e) {
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.of("error", e.getReason() == null ? "Request failed." : e.getReason()));
    }
}
