package com.example.tsldemo.AgentAPI;

import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.example.tsldemo.ApiDTOS.*;


/**
 * The browser-facing face of the LLM ("newsroom") service.
 *
 * Everything here is a RELAY, not a reinterpretation: bodies and status codes are passed through
 * untouched (see AgentService.JSON_OBJECT for why they are carried as raw JSON rather than through
 * typed DTOs). Only {@link NewsroomRunner} consumes the contract in typed form, because it acts on
 * it rather than forwarding it.
 */
@RestController
public class AgentController {
	private final AgentService service;
	private final BriefIdentity identity;
	private final TaskAccess access;

	// Constructor injection rather than @Autowired on the field: it makes the dependency explicit
	// and final, and lets a test stand the controller up without a Spring context.
	public AgentController(AgentService service, BriefIdentity identity, TaskAccess access) {
		this.service = service;
		this.identity = identity;
		this.access = access;
	}

	/** The caller's credential, from the header or — for EventSource, which cannot set headers —
	 *  the `access_token` query parameter. Normalised to the `Bearer …` form JwtUtil expects. */
	private static String credential(String authHeader, String accessToken) {
		if (authHeader != null && !authHeader.isBlank()) {
			return authHeader;
		}
		return (accessToken == null || accessToken.isBlank()) ? null : "Bearer " + accessToken;
	}

	@PostMapping("/text")
    public GenerateTextResponse generateText(@RequestBody GenerateTextRequest request) {
        return service.generateText(request);
    }

    @PostMapping("/brand-card")
    public GenerateHtmlResponse generateHtmlCard(@RequestBody GenerateHtmlRequest request) {
        return service.generateHtmlCard(request);
    }

    /** Routes one chat turn: a single post now, or a whole campaign. Stateless upstream. */
    @PostMapping("/intake/classify")
    public ResponseEntity<Map<String, Object>> intakeClassify(
            @RequestBody Map<String, Object> body) {
        return service.relayIntakeClassify(body);
    }

    @PostMapping("/tasks/{taskId}/render-video")
    public ResponseEntity<Map<String, Object>> renderVideo(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relayRenderVideo(taskId, body);
    }

    @GetMapping("/video-jobs/{jobId}")
    public ResponseEntity<Map<String, Object>> getVideoJob(@PathVariable String jobId) {
        return service.relayVideoJob(jobId);
    }

    @GetMapping(value = "/video-jobs/{jobId}/download", produces = "video/mp4")
    public ResponseEntity<byte[]> downloadVideo(@PathVariable String jobId) {
        byte[] video = service.downloadVideo(jobId);
        return ResponseEntity.ok()
                .contentType(MediaType.valueOf("video/mp4"))
                .body(video);
    }

	/**
	 * Start a run.
	 *
	 * The brief's identity is re-derived from the caller's signed token and any `business_id` /
	 * `user_id` the body carried is discarded — see {@link BriefIdentity}. This is the one call
	 * that establishes which brand a run reads and writes, so it is the one that has to be right.
	 */
	@PostMapping("/tasks")
	public ResponseEntity<Map<String, Object>> startTask(
			@RequestBody Map<String, Object> brief,
			@RequestHeader(value = "Authorization", required = false) String authHeader) {
		ResponseEntity<Map<String, Object>> started = service.relayStartTask(identity.stamp(brief, authHeader));
		// Claim the run for this caller, so nobody else can read or steer it afterwards. Only
		// meaningful on success — a rejected start has no task to own.
		if (started.getStatusCode().is2xxSuccessful() && started.getBody() != null) {
			Object taskId = started.getBody().get("task_id");
			if (taskId != null) {
				access.remember(String.valueOf(taskId), authHeader);
			}
		}
		return started;
	}

	// NB every path below is `/tasks/{taskId}/…`. They used to be mounted at `/{taskId}/…` — which
	// both diverged from the LLM service's own paths (so a proxy could not mirror them 1:1) and,
	// in the case of the bare `GET /{taskId}`, matched EVERY single-segment GET in the application.

	@PostMapping("/tasks/{taskId}/review")
    public ResponseEntity<Map<String, Object>> submitReview(
            @PathVariable String taskId, @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relayReview(taskId, body);
    }

    @PostMapping("/tasks/{taskId}/confirm-learning")
    public ResponseEntity<Map<String, Object>> confirmLearning(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relayConfirmLearning(taskId, body);
    }

    @GetMapping("/tasks/{taskId}")
    public ResponseEntity<Map<String, Object>> getTaskSnapshot(
            @PathVariable String taskId,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relayTaskSnapshot(taskId);
    }

    @PostMapping("/tasks/{taskId}/raise-hand")
    public ResponseEntity<Map<String, Object>> raiseHand(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relayRaiseHand(taskId, body);
    }

    @PostMapping("/tasks/{taskId}/say")
    public ResponseEntity<Map<String, Object>> say(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relaySay(taskId, body);
    }

    @PostMapping("/tasks/{taskId}/round-control")
    public ResponseEntity<Map<String, Object>> roundControl(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {
        access.assertMayAccess(taskId, authHeader);
        return service.relayRoundControl(taskId, body);
    }

    /**
     * One roundtable turn's TTS clip, referenced by an `agent_utterance_audio` event's `audio_url`.
     *
     * The path mirrors the upstream one exactly, so a client can take the `audio_url` off the event
     * and prefix this service's base URL. A 404 means "no audio for that turn" and is normal.
     */
    @GetMapping(value = "/tasks/{taskId}/audio/{tableId}/{speaker}/{roundIndex}")
    public ResponseEntity<byte[]> turnAudio(
            @PathVariable String taskId,
            @PathVariable String tableId,
            @PathVariable String speaker,
            @PathVariable int roundIndex,
            @RequestHeader(value = "Authorization", required = false) String authHeader,
            @RequestParam(value = "access_token", required = false) String accessToken) {
        // An <audio> element sets no headers either, so this takes the same query-parameter
        // fallback as the event stream. The clip is a persona reading this run's discussion aloud.
        access.assertMayAccess(taskId, credential(authHeader, accessToken));
        ResponseEntity<byte[]> upstream = service.relayTurnAudio(taskId, tableId, speaker, roundIndex);
        if (!upstream.getStatusCode().is2xxSuccessful()) {
            return ResponseEntity.status(upstream.getStatusCode()).build();
        }
        return ResponseEntity.ok()
                .contentType(MediaType.valueOf("audio/mpeg"))
                .cacheControl(org.springframework.http.CacheControl.noStore())
                .body(upstream.getBody());
    }

    /**
     * Relay one task's SSE stream to the browser.
     *
     * Two details carry the whole resume story, and both fail SILENTLY if dropped:
     *  - `Last-Event-ID` is forwarded UPSTREAM, so the LLM service replays only what we missed;
     *  - each relayed frame is re-stamped with its `seq` as the SSE `id:`, so the browser's
     *    EventSource knows where it got to and sends that id back on its own reconnect.
     * Without the `id:` the browser has nothing to resume from and re-reads the entire run every
     * time the connection blips.
     */
    @GetMapping(
    	    value = "/tasks/{taskId}/events",
    	    produces = MediaType.TEXT_EVENT_STREAM_VALUE
    	)
    	public SseEmitter events(
    	        @PathVariable String taskId,
    	        @RequestHeader(value = "Last-Event-ID", required = false) String lastEventId,
    	        @RequestHeader(value = "Authorization", required = false) String authHeader,
    	        @RequestParam(value = "access_token", required = false) String accessToken) {

    	    // EventSource cannot set request headers, so the token may arrive as a query parameter
    	    // instead. Without accepting it, an owned run's stream would be the one hole left in the
    	    // ownership check — and it is the one carrying the drafts and the whole discussion.
    	    access.assertMayAccess(taskId, credential(authHeader, accessToken));

    	    SseEmitter emitter = new SseEmitter(Long.MAX_VALUE);

    	    Thread upstream = service.consumeEvents(taskId, lastEventId, event -> {
    	        try {
    	            SseEmitter.SseEventBuilder frame = SseEmitter.event().name("message").data(event);
    	            Object seq = event.get("seq");
    	            if (seq != null) {
    	                frame = frame.id(String.valueOf(seq));
    	            }
    	            emitter.send(frame);
    	        } catch (Exception e) {
    	            emitter.completeWithError(e);
    	        }
    	    });

    	    // The upstream stream ends when the run finishes (or the connection drops); complete the
    	    // browser's stream too instead of leaving it open forever waiting on a dead producer.
    	    Thread closer = new Thread(() -> {
    	        try {
    	            upstream.join();
    	            emitter.complete();
    	        } catch (InterruptedException e) {
    	            Thread.currentThread().interrupt();
    	        }
    	    });
    	    closer.setDaemon(true);
    	    closer.start();

    	    return emitter;
    	}

}
