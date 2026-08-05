package com.example.tsldemo.AgentAPI;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;

/**
 * The browser-facing half of SSE resume.
 *
 * {@link AgentServiceRelayTest} covers the upstream half (forwarding `Last-Event-ID`). This covers
 * the downstream half: re-stamping each relayed frame with an `id:`. Both are required — with the
 * header alone the service would resume from a marker the browser never learned, and with the id
 * alone the marker the browser sends back would be discarded on its way up.
 */
class AgentControllerSseTest {

    private static Map<String, Object> event(int seq, String type) {
        Map<String, Object> ev = new LinkedHashMap<>();
        ev.put("type", type);
        ev.put("seq", seq);
        return ev;
    }

    /** An AgentService whose event stream delivers `events` synchronously, then ends. */
    private static AgentService streaming(Map<String, Object>... events) {
        AgentService service = mock(AgentService.class);
        when(service.consumeEvents(anyString(), any(), any())).thenAnswer(invocation -> {
            Consumer<Map<String, Object>> onEvent = invocation.getArgument(2);
            for (Map<String, Object> ev : events) {
                onEvent.accept(ev);
            }
            return new Thread(() -> { });  // never started: join() returns at once
        });
        return service;
    }

    private static MockMvc mvc(AgentService service) {
        // A permissive TaskAccess: ownership is covered on its own in TaskAccessTest, and mixing
        // it in here would make these tests fail for reasons that have nothing to do with SSE.
        return MockMvcBuilders
                .standaloneSetup(new AgentController(service, null, mock(TaskAccess.class)))
                .build();
    }

    @Test
    @DisplayName("each relayed frame carries its seq as the SSE id")
    void framesCarryAnId() throws Exception {
        MockMvc mvc = mvc(streaming(event(3, "progress"), event(4, "agent_utterance")));

        MvcResult started = mvc.perform(MockMvcRequestBuilders.get("/tasks/t1/events")).andReturn();
        String body = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                .asyncDispatch(started)).andReturn().getResponse().getContentAsString();

        // Without these the browser's EventSource has nothing to remember, so its automatic
        // reconnect starts from scratch and replays the entire run every time.
        assertThat(body).contains("id:3").contains("id:4");
        assertThat(body).contains("\"seq\":3").contains("\"seq\":4");
    }

    @Test
    @DisplayName("the browser's Last-Event-ID is handed to the upstream stream")
    void resumeMarkerReachesUpstream() throws Exception {
        AgentService service = streaming(event(9, "progress"));
        MockMvc mvc = mvc(service);

        MvcResult started = mvc.perform(MockMvcRequestBuilders.get("/tasks/t1/events")
                .header("Last-Event-ID", "8")).andReturn();
        mvc.perform(MockMvcRequestBuilders.asyncDispatch(started)).andReturn();

        verify(service).consumeEvents(eq("t1"), eq("8"), any());
    }

    @Test
    @DisplayName("a first connect passes no marker up")
    void firstConnectPassesNothing() throws Exception {
        AgentService service = streaming(event(0, "progress"));
        MockMvc mvc = mvc(service);

        MvcResult started = mvc.perform(MockMvcRequestBuilders.get("/tasks/t1/events")).andReturn();
        mvc.perform(MockMvcRequestBuilders.asyncDispatch(started)).andReturn();

        verify(service).consumeEvents(eq("t1"), eq(null), any());
    }

    @Test
    @DisplayName("a compliance block survives the SSE relay intact")
    void complianceBlockSurvivesTheRelay() throws Exception {
        // The gate re-opens over SSE, not just on the snapshot, and these three keys are how a
        // client knows a plain `approve` will now be refused. Relaying them through a typed DTO
        // would have deleted them silently; this pins the untyped path that replaced it.
        Map<String, Object> blocked = new LinkedHashMap<>();
        blocked.put("type", "result");
        blocked.put("status", "draft_ready");
        blocked.put("platform", "linkedin");
        blocked.put("seq", 7);
        blocked.put("draft", "the copy that tripped the screen");
        blocked.put("blocked", true);
        blocked.put("block_reason", "self-harm");
        blocked.put("allowed_decisions", java.util.List.of("approve_after_edit", "reject", "discard"));

        MockMvc mvc = mvc(streaming(blocked));
        MvcResult started = mvc.perform(MockMvcRequestBuilders.get("/tasks/t1/events")).andReturn();
        String body = mvc.perform(MockMvcRequestBuilders.asyncDispatch(started))
                .andReturn().getResponse().getContentAsString();

        assertThat(body).contains("\"blocked\":true");
        assertThat(body).contains("\"block_reason\":\"self-harm\"");
        assertThat(body).contains("approve_after_edit").contains("reject").contains("discard");
        // …and `approve` is NOT among them: offering it would be offering a button the service
        // answers 400 to.
        assertThat(body).doesNotContain("\"approve\"");
    }

    @Test
    @DisplayName("a turn's audio is served as mpeg bytes, and a missing clip as a 404")
    void audioIsServedAsBytes() throws Exception {
        byte[] mp3 = {(byte) 0xFF, (byte) 0xFB, 0x10};
        AgentService service = mock(AgentService.class);
        when(service.relayTurnAudio("t1", "linkedin", "brand_voice", 2))
                .thenReturn(ResponseEntity.ok(mp3));
        when(service.relayTurnAudio("t1", "linkedin", "brand_voice", 9))
                .thenReturn(ResponseEntity.status(404).build());

        MockMvc mvc = mvc(service);

        byte[] served = mvc.perform(
                MockMvcRequestBuilders.get("/tasks/t1/audio/linkedin/brand_voice/2"))
                .andReturn().getResponse().getContentAsByteArray();
        assertThat(served).isEqualTo(mp3);

        int status = mvc.perform(
                MockMvcRequestBuilders.get("/tasks/t1/audio/linkedin/brand_voice/9"))
                .andReturn().getResponse().getStatus();
        assertThat(status).isEqualTo(404);
    }

    @Test
    @DisplayName("task routes live under /tasks, so a proxy can mirror the upstream paths 1:1")
    void taskRoutesAreMountedUnderTasks() throws Exception {
        AgentService service = mock(AgentService.class);
        when(service.relayTaskSnapshot("t1")).thenReturn(ResponseEntity.ok(Map.of("task_id", "t1")));
        MockMvc mvc = mvc(service);

        assertThat(mvc.perform(MockMvcRequestBuilders.get("/tasks/t1"))
                .andReturn().getResponse().getStatus()).isEqualTo(200);

        // The old mapping was a bare `/{taskId}`, which matched EVERY single-segment GET in the
        // application — a routing landmine as well as a path a proxy could not mirror.
        assertThat(mvc.perform(MockMvcRequestBuilders.get("/t1"))
                .andReturn().getResponse().getStatus()).isEqualTo(404);
    }
}
