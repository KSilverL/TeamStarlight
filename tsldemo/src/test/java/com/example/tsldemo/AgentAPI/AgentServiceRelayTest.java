package com.example.tsldemo.AgentAPI;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClient;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

/**
 * The proxy layer in front of the Python LLM service.
 *
 * These are the behaviours a browser depends on and that fail QUIETLY when they regress — a
 * dropped header, a swallowed field, a 409 turned into a 500. A real (loopback) HTTP server stands
 * in for the LLM service so the actual request-building and response-shaping code runs, rather
 * than a mock that would agree with whatever the code happened to do.
 */
class AgentServiceRelayTest {

    private HttpServer server;
    private AgentService service;

    /** Requests the fake LLM service received, so a test can assert on what we SENT. */
    private final List<RecordedRequest> received = new ArrayList<>();

    private record RecordedRequest(String method, String path, String lastEventId, String body) {}

    @BeforeEach
    void startFakeLlmService() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.start();

        service = new AgentService(RestClient.builder().build());
        Field baseUrl = AgentService.class.getDeclaredField("llmServiceBaseUrl");
        baseUrl.setAccessible(true);
        baseUrl.set(service, "http://127.0.0.1:" + server.getAddress().getPort());
    }

    @AfterEach
    void stopFakeLlmService() {
        server.stop(0);
    }

    /** Register a handler that records the request and answers with a fixed status + body. */
    private void stub(String path, int status, String contentType, byte[] body) {
        server.createContext(path, exchange -> {
            received.add(record(exchange));
            exchange.getResponseHeaders().set("Content-Type", contentType);
            exchange.sendResponseHeaders(status, body.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(body);
            }
        });
    }

    private void stubJson(String path, int status, String json) {
        stub(path, status, "application/json", json.getBytes(StandardCharsets.UTF_8));
    }

    private static RecordedRequest record(HttpExchange exchange) throws IOException {
        String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        return new RecordedRequest(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getPath(),
                exchange.getRequestHeaders().getFirst("Last-Event-ID"),
                body);
    }

    // ── Losslessness ─────────────────────────────────────────────────────────

    @Test
    @DisplayName("a relayed snapshot keeps fields no Java DTO declares")
    void relayIsLossless() {
        // Exactly the shape a compliance block produces. Routing this through the typed
        // TaskSnapshot/Pending records would silently delete every key below that they do not
        // declare — and the browser needs `blocked`/`allowed_decisions` to know a plain approve
        // is no longer accepted, and `discarded` to explain a platform that produced no output.
        stubJson("/tasks/t1", 200, """
                {"task_id":"t1","status":"awaiting_review",
                 "pending":[{"request_id":"r1","platform":"linkedin","draft":"hi","comment":"nope",
                             "needs_human_intervention":true,"blocked":true,
                             "block_reason":"self-harm","allowed_decisions":["approve_after_edit","reject","discard"]}],
                 "outputs":[],"discarded":[{"platform":"instagram","reason":"gave up"}],
                 "preference_summary":{"skills":[]}}""");

        ResponseEntity<Map<String, Object>> response = service.relayTaskSnapshot("t1");

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        Map<String, Object> body = response.getBody();
        assertThat(body).containsKeys("discarded", "preference_summary");

        @SuppressWarnings("unchecked")
        Map<String, Object> pending = ((List<Map<String, Object>>) body.get("pending")).get(0);
        assertThat(pending.get("blocked")).isEqualTo(true);
        assertThat(pending.get("block_reason")).isEqualTo("self-harm");
        assertThat(pending.get("allowed_decisions"))
                .isEqualTo(List.of("approve_after_edit", "reject", "discard"));
    }

    // ── Status passthrough ───────────────────────────────────────────────────

    @Test
    @DisplayName("upstream 4xx is relayed with its status and explanation, not raised as a 500")
    void errorsArePassedThrough() {
        // 409 is the LLM service's "this run was recovered from storage after a restart and cannot
        // be resumed". RestClient's DEFAULT behaviour is to throw on 4xx, which Spring renders as a
        // 500 — turning a precise, actionable answer into "something broke".
        stubJson("/tasks/gone/review", 409, """
                {"error":"task gone was recovered from storage after a restart"}""");

        ResponseEntity<Map<String, Object>> response =
                service.relayReview("gone", Map.of("verdicts", Map.of()));

        assertThat(response.getStatusCode().value()).isEqualTo(409);
        assertThat(String.valueOf(response.getBody().get("error"))).contains("recovered from storage");
    }

    @Test
    @DisplayName("a 400 from a bad verdict reaches the caller as a 400")
    void badRequestIsPassedThrough() {
        stubJson("/tasks/t1/review", 400, """
                {"error":"'decision' must be one of approve_after_edit, reject, discard"}""");

        ResponseEntity<Map<String, Object>> response =
                service.relayReview("t1", Map.of("verdicts", Map.of()));

        assertThat(response.getStatusCode().value()).isEqualTo(400);
        assertThat(String.valueOf(response.getBody().get("error"))).contains("must be one of");
    }

    // ── Turn audio ───────────────────────────────────────────────────────────

    @Test
    @DisplayName("a turn's clip is relayed as bytes, and a missing one as a plain 404")
    void audioIsRelayedAsBytes() {
        byte[] mp3 = {(byte) 0xFF, (byte) 0xFB, 0x10, 0x00, 0x42};
        stub("/tasks/t1/audio/linkedin/brand_voice/2", 200, "audio/mpeg", mp3);
        stubJson("/tasks/t1/audio/linkedin/brand_voice/9", 404, "{\"error\":\"no audio for that turn\"}");

        ResponseEntity<byte[]> ok = service.relayTurnAudio("t1", "linkedin", "brand_voice", 2);
        assertThat(ok.getStatusCode().value()).isEqualTo(200);
        // Byte-exact: decoding an mp3 as text would corrupt it beyond recognition.
        assertThat(ok.getBody()).isEqualTo(mp3);

        ResponseEntity<byte[]> missing = service.relayTurnAudio("t1", "linkedin", "brand_voice", 9);
        assertThat(missing.getStatusCode().value()).isEqualTo(404);
    }

    @Test
    @DisplayName("path segments are encoded rather than pasted into the upstream URL")
    void pathSegmentsAreEncoded() {
        stubJson("/tasks/a%2Fb", 200, "{\"task_id\":\"a/b\"}");

        service.relayTaskSnapshot("a/b");

        // The slash must arrive encoded; pasted raw it would silently address a DIFFERENT resource.
        assertThat(received).isNotEmpty();
        assertThat(received.get(received.size() - 1).path()).doesNotContain("/tasks/a/b");
    }

    // ── SSE resume ───────────────────────────────────────────────────────────

    @Test
    @DisplayName("Last-Event-ID is forwarded upstream so a reconnect resumes")
    void lastEventIdIsForwarded() throws Exception {
        // THE silent failure: if this header is dropped, nothing errors — resume just never
        // engages and every reconnect replays the whole run again.
        server.createContext("/tasks/t1/events", exchange -> {
            received.add(record(exchange));
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            // Terminal, so the follower stops rather than reconnecting — reconnect-on-drop is
            // covered by `aDroppedStreamIsResumed`; this test is only about the header.
            byte[] frame = ("id: 8\ndata: {\"seq\":8,\"type\":\"progress\",\"node\":\"workflow\","
                    + "\"status\":\"done\"}\n\n").getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, frame.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(frame);
            }
        });

        CountDownLatch delivered = new CountDownLatch(1);
        List<Map<String, Object>> events = new ArrayList<>();
        service.consumeEvents("t1", "7", event -> {
            events.add(event);
            delivered.countDown();
        }).join();

        assertThat(delivered.await(5, TimeUnit.SECONDS)).isTrue();
        assertThat(received).hasSize(1);
        assertThat(received.get(0).lastEventId()).isEqualTo("7");
        assertThat(events).hasSize(1);
        assertThat(events.get(0).get("seq")).isEqualTo(8);
    }

    @Test
    @DisplayName("a stream cut short is re-established, resuming from the last seq seen")
    void aDroppedStreamIsResumed() throws Exception {
        // A run sits at the human gate for as long as the person takes, so its stream WILL be cut
        // by an idle proxy or a blip. Reading it once meant the first cut ended it permanently and
        // silently — the caller simply stopped hearing about a run that was still going.
        List<String> resumeMarkers = new ArrayList<>();
        server.createContext("/tasks/t3/events", exchange -> {
            String marker = exchange.getRequestHeaders().getFirst("Last-Event-ID");
            resumeMarkers.add(marker);
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            // First connect: two events, then the stream just ends — the run is NOT over.
            // Second connect: the terminal event, so the follower stops.
            String frames = marker == null
                    ? "id: 0\ndata: {\"seq\":0,\"type\":\"progress\",\"node\":\"creator\"}\n\n"
                      + "id: 1\ndata: {\"seq\":1,\"type\":\"progress\",\"node\":\"reviewer\"}\n\n"
                    : "id: 2\ndata: {\"seq\":2,\"type\":\"progress\",\"node\":\"workflow\",\"status\":\"done\"}\n\n";
            byte[] body = frames.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(body);
            }
        });

        List<Map<String, Object>> events = new ArrayList<>();
        service.consumeEvents("t3", null, events::add).join();

        // Reconnected once, and asked to resume from the last event it actually saw — so the
        // service replays only what was missed instead of the whole run again.
        assertThat(resumeMarkers).containsExactly(null, "1");
        assertThat(events.stream().map(e -> e.get("seq"))).containsExactly(0, 1, 2);
    }

    @Test
    @DisplayName("the follower stops on the run's terminal event instead of reconnecting forever")
    void terminalEventEndsTheFollow() throws Exception {
        List<String> connects = new ArrayList<>();
        server.createContext("/tasks/t4/events", exchange -> {
            connects.add(exchange.getRequestURI().getPath());
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            byte[] body = ("id: 0\ndata: {\"seq\":0,\"type\":\"progress\",\"node\":\"workflow\","
                    + "\"status\":\"done\"}\n\n").getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(body);
            }
        });

        service.consumeEvents("t4", null, event -> { }).join();

        assertThat(connects).hasSize(1);
    }

    @Test
    @DisplayName("a first connect sends no resume marker")
    void firstConnectHasNoMarker() throws Exception {
        server.createContext("/tasks/t2/events", exchange -> {
            received.add(record(exchange));
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            byte[] frame = ("id: 0\ndata: {\"seq\":0,\"type\":\"progress\",\"node\":\"workflow\","
                    + "\"status\":\"done\"}\n\n").getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, frame.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(frame);
            }
        });

        service.consumeEvents("t2", event -> { }).join();

        assertThat(received).hasSize(1);
        assertThat(received.get(0).lastEventId()).isNull();
    }
}
