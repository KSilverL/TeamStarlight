package com.example.tsldemo.AgentAPI;

import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Consumer;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import java.util.stream.Stream;

import java.net.http.HttpResponse;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;

import com.example.tsldemo.ApiDTOS.*;

import tools.jackson.databind.ObjectMapper;


@Service
public class AgentService {
	private final RestClient restClient;
	private final ObjectMapper mapper = new ObjectMapper();

	private final HttpClient http = HttpClient.newHttpClient();

	@Value("${llm.service.base-url:http://localhost:8080}")
	private String llmServiceBaseUrl;

	public AgentService(RestClient restClient) {
        this.restClient = restClient;
    }

	/** Untyped JSON object — what the relay methods below carry.
	 *
	 *  Relaying through a typed DTO would be LOSSY: Jackson drops every field the record does not
	 *  declare, so re-serializing it to the browser silently deletes them. That is not theoretical
	 *  here — the LLM service's gate carries `blocked` / `block_reason` / `allowed_decisions` when
	 *  the compliance screen trips, and the snapshot carries `discarded` / `preference_summary`,
	 *  none of which {@link ApiDTOS.Pending} or {@link ApiDTOS.TaskSnapshot} declare. A proxy must
	 *  not decide which half of a contract its callers are allowed to see. */
	private static final ParameterizedTypeReference<Map<String, Object>> JSON_OBJECT =
			new ParameterizedTypeReference<>() {};

	/** Relay a GET, preserving the upstream status code AND the full body.
	 *
	 *  Errors are passed through rather than thrown: the LLM service answers with meaningful
	 *  statuses (400 a bad verdict, 404 unknown task, 409 "recovered after a restart — this run
	 *  cannot be resumed") and a `{"error": …}` body explaining them. RestClient's default handler
	 *  turns any 4xx into an exception, which Spring then renders as a 500 — converting a precise,
	 *  actionable answer into "something broke". */
	private ResponseEntity<Map<String, Object>> relayGet(String path) {
		return restClient.get()
				.uri(llmServiceBaseUrl + path)
				.retrieve()
				.onStatus(HttpStatusCode::isError, (request, response) -> { })
				.toEntity(JSON_OBJECT);
	}

	/** Relay a POST. Same status/body passthrough contract as {@link #relayGet}. */
	private ResponseEntity<Map<String, Object>> relayPost(String path, Object body) {
		return restClient.post()
				.uri(llmServiceBaseUrl + path)
				.contentType(MediaType.APPLICATION_JSON)
				.body(body)
				.retrieve()
				.onStatus(HttpStatusCode::isError, (request, response) -> { })
				.toEntity(JSON_OBJECT);
	}

	private <T> T post(String path, Object request, Class<T> responseType) {
	    return restClient.post()
	            .uri(llmServiceBaseUrl + path)
	            .contentType(MediaType.APPLICATION_JSON)
	            .body(request)
	            .retrieve()
	            .body(responseType);
	}

	private <T> T get(String path, Class<T> responseType) {
        return restClient.get()
                .uri(llmServiceBaseUrl + path)
                .retrieve()
                .body(responseType);
    }

	
	public GenerateTextResponse generateText(GenerateTextRequest request) {
        return post("/generate-text", request, GenerateTextResponse.class);
    }

    public GenerateHtmlResponse generateHtmlCard(GenerateHtmlRequest request) {
        return post("/generate", request, GenerateHtmlResponse.class);
    }

    public RenderVideoResponse renderVideo(String taskId, String platform) {
        return post(
            "/tasks/" + taskId + "/render-video",
            new RenderVideoRequest(platform),
            RenderVideoResponse.class
        );
    }

    public VideoJobResponse getVideoJob(String jobId) {
        return get("/video-jobs/" + jobId, VideoJobResponse.class);
    }

    public byte[] downloadVideo(String jobId) {
        return restClient.get()
                .uri(llmServiceBaseUrl + "/video-jobs/" + jobId + "/download")
                .retrieve()
                .body(byte[].class);
    }
	
	public TaskSnapshot getTaskSnapshot(String taskId) {
	    return restClient.get()
	            .uri(llmServiceBaseUrl + "/tasks/" + taskId)
	            .retrieve()
	            .body(TaskSnapshot.class);
	}
	
	public TaskSnapshot startTask(CreativeBrief brief) {
		return restClient.post()
                .uri(llmServiceBaseUrl + "/tasks")
                .contentType(MediaType.APPLICATION_JSON)
                .body(brief)
                .retrieve()
                .body(TaskSnapshot.class);
	}
	
	public TaskSnapshot reviewTask(String taskId, ReviewRequest request) {
	    return post(
	            "/tasks/" + taskId + "/review",
	            request,
	            TaskSnapshot.class
	    );
	}
	
	public ConfirmLearningResponse agentConfirmLearning(Boolean learn, String taskId) {
	    return post(
	            "/tasks/" + taskId + "/confirm-learning",
	            new ConfirmLearningRequest(learn),
	            ConfirmLearningResponse.class
	    );
	}

	public RaiseHandResponse agentRaiseHand(String taskId, String tableId) {
	    return post(
	            "/tasks/" + taskId + "/raise-hand",
	            new RaiseHandRequest(tableId),
	            RaiseHandResponse.class
	    );
	}

	public SayResponse agentSay(String taskId, SayRequest request) {
	    return post(
	            "/tasks/" + taskId + "/say",
	            request,
	            SayResponse.class
	    );
	}

	public RoundControlResponse agentRoundControl(String taskId, RoundControlRequest request) {
	    return post(
	            "/tasks/" + taskId + "/round-control",
	            request,
	            RoundControlResponse.class
	    );
	}
	
	
	// ── Transparent relays for the browser-facing proxy (see JSON_OBJECT on losslessness) ──────

	public ResponseEntity<Map<String, Object>> relayStartTask(Map<String, Object> brief) {
		return relayPost("/tasks", brief);
	}

	public ResponseEntity<Map<String, Object>> relayTaskSnapshot(String taskId) {
		return relayGet("/tasks/" + enc(taskId));
	}

	public ResponseEntity<Map<String, Object>> relayReview(String taskId, Map<String, Object> body) {
		return relayPost("/tasks/" + enc(taskId) + "/review", body);
	}

	public ResponseEntity<Map<String, Object>> relayConfirmLearning(String taskId, Map<String, Object> body) {
		return relayPost("/tasks/" + enc(taskId) + "/confirm-learning", body);
	}

	public ResponseEntity<Map<String, Object>> relayRaiseHand(String taskId, Map<String, Object> body) {
		return relayPost("/tasks/" + enc(taskId) + "/raise-hand", body);
	}

	public ResponseEntity<Map<String, Object>> relaySay(String taskId, Map<String, Object> body) {
		return relayPost("/tasks/" + enc(taskId) + "/say", body);
	}

	public ResponseEntity<Map<String, Object>> relayRoundControl(String taskId, Map<String, Object> body) {
		return relayPost("/tasks/" + enc(taskId) + "/round-control", body);
	}

	public ResponseEntity<Map<String, Object>> relayRenderVideo(String taskId, Map<String, Object> body) {
		return relayPost("/tasks/" + enc(taskId) + "/render-video", body);
	}

	public ResponseEntity<Map<String, Object>> relayVideoJob(String jobId) {
		return relayGet("/video-jobs/" + enc(jobId));
	}

	public ResponseEntity<Map<String, Object>> relayIntakeClassify(Map<String, Object> body) {
		return relayPost("/intake/classify", body);
	}

	/** One roundtable turn's TTS clip.
	 *
	 *  Fetched as bytes, never as a String: it is an mp3, and decoding it as text would corrupt it.
	 *  A 404 here is ordinary — "no audio for that turn" (never synthesized, the human seat is not
	 *  read back, or the clip aged out of the service's bounded cache) — so it is relayed as a 404
	 *  rather than raised, matching how the LLM service documents it. */
	public ResponseEntity<byte[]> relayTurnAudio(
			String taskId, String tableId, String speaker, int roundIndex) {
		return restClient.get()
				.uri(llmServiceBaseUrl + "/tasks/" + enc(taskId) + "/audio/" + enc(tableId)
						+ "/" + enc(speaker) + "/" + roundIndex)
				.retrieve()
				.onStatus(HttpStatusCode::isError, (request, response) -> { })
				.toEntity(byte[].class);
	}

	/** Percent-encode one path segment. The ids are service-generated and tame today, but a proxy
	 *  that pastes caller-supplied text straight into an upstream URL is how path traversal and
	 *  request splitting get in. */
	private static String enc(String segment) {
		return URLEncoder.encode(segment == null ? "" : segment, StandardCharsets.UTF_8)
				.replace("+", "%20");
	}

	/**
	 * Follow one task's SSE stream, handing each event to {@code onEvent}.
	 *
	 * {@code lastEventId} resumes a dropped connection: the LLM service stamps every frame with an
	 * `id:` (equal to the event's `seq`) and replays only what came after the id we send back. It
	 * MUST be forwarded — dropping it does not fail, it silently disables resume, and every
	 * reconnect replays the entire run again with nothing anywhere to show for it.
	 *
	 * @return the daemon thread following the stream, so the caller can join/observe it.
	 */
	public Thread consumeEvents(String taskId, String lastEventId, Consumer<Map<String, Object>> onEvent) {
	    Thread t = new Thread(() -> followStream(taskId, lastEventId, onEvent));
	    t.setDaemon(true);
	    t.start();
	    return t;
	}

	/** How many times a dropped stream is re-established before giving up on the run. */
	private static final int MAX_RECONNECTS = 20;

	/** Pause before re-establishing, so a service that is down is not hammered. */
	private static final long RECONNECT_BACKOFF_MS = 1_000;

	/**
	 * Follow one task's event stream to its end, RE-ESTABLISHING it if it drops.
	 *
	 * A run sits at the human gate for as long as the person takes, so its stream is long-lived and
	 * will be cut by an idle proxy, a network blip or a restart somewhere in between. Reading it
	 * once means the first such cut ends the stream permanently, silently — the caller simply stops
	 * hearing about a run that is still going.
	 *
	 * Resuming is what makes reconnecting cheap rather than duplicative: each event's `seq` is kept
	 * and sent back as `Last-Event-ID`, so the service replays only what was missed instead of the
	 * whole run. Without that, every blip would re-deliver every event and re-fire whatever the
	 * caller does with them.
	 *
	 * It stops on the run's own terminal event, and is bounded by {@link #MAX_RECONNECTS} so a
	 * service that never answers cannot keep a thread spinning forever.
	 */
	private void followStream(String taskId, String lastEventId, Consumer<Map<String, Object>> onEvent) {
	    String marker = lastEventId;
	    boolean[] finished = {false};

	    for (int attempt = 0; attempt <= MAX_RECONNECTS && !finished[0]; attempt++) {
	        String resumeFrom = marker;
	        String[] latest = {marker};
	        try {
	            HttpRequest.Builder builder = HttpRequest.newBuilder()
	                    .uri(URI.create(llmServiceBaseUrl + "/tasks/" + enc(taskId) + "/events"))
	                    .GET();
	            if (resumeFrom != null && !resumeFrom.isBlank()) {
	                builder.header("Last-Event-ID", resumeFrom);
	            }

	            HttpResponse<Stream<String>> response =
	                    http.send(builder.build(), HttpResponse.BodyHandlers.ofLines());

	            response.body()
	                    .filter(line -> line.startsWith("data: "))
	                    .forEach(line -> {
	                        try {
	                            Map<String, Object> ev = mapper.readValue(line.substring(6), Map.class);
	                            Object seq = ev.get("seq");
	                            if (seq != null) {
	                                latest[0] = String.valueOf(seq);
	                            }
	                            if (isTerminal(ev)) {
	                                finished[0] = true;
	                            }
	                            onEvent.accept(ev);
	                        } catch (Exception e) {
	                            e.printStackTrace();
	                        }
	                    });
	        } catch (Exception e) {
	            e.printStackTrace(); // a genuine connection error — retried below
	        }

	        marker = latest[0];
	        if (finished[0]) {
	            return;
	        }
	        // The stream ended without the run ending. Progress resets the budget, so a long run
	        // that blips repeatedly is fine; only a stream that goes nowhere exhausts the attempts.
	        if (!java.util.Objects.equals(marker, resumeFrom)) {
	            attempt = -1;
	        }
	        try {
	            Thread.sleep(RECONNECT_BACKOFF_MS);
	        } catch (InterruptedException interrupted) {
	            Thread.currentThread().interrupt();
	            return;
	        }
	    }
	}

	/** The run's own last word: a `workflow` progress event that is done or errored. Everything
	 *  else — including the gate pausing — leaves the run live and the stream worth resuming. */
	private static boolean isTerminal(Map<String, Object> event) {
	    return "progress".equals(event.get("type"))
	            && "workflow".equals(event.get("node"))
	            && ("done".equals(event.get("status")) || "error".equals(event.get("status")));
	}

	/** First connect (no resume marker) — the full replay. */
	public Thread consumeEvents(String taskId, Consumer<Map<String, Object>> onEvent) {
		return consumeEvents(taskId, null, onEvent);
	}


}
