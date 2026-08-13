package com.example.tsldemo.AgentAPI;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import com.example.tsldemo.ApiDTOS.CreativeBrief;
import com.example.tsldemo.ApiDTOS.Pending;
import com.example.tsldemo.ApiDTOS.ReviewRequest;
import com.example.tsldemo.ApiDTOS.TaskSnapshot;
import com.example.tsldemo.ApiDTOS.Verdict;
import com.example.tsldemo.SessionAPI.SessionService;

/**
 * The unattended driver's behaviour at the gate.
 *
 * The LLM service's compliance screen is unbounded BY DESIGN — safe only because a human verdict
 * paces every lap. Driving it automatically removes that pacing, so what this class does with a
 * blocked gate is a safety property, not a preference.
 */
class NewsroomRunnerTest {

    private static Pending ordinary(String platform) {
        return new Pending("r-" + platform, platform, "draft", "looks good", false,
                false, null, null);
    }

    private static Pending blocked(String platform, String reason) {
        return new Pending("r-" + platform, platform, "draft", "not compliant", true,
                true, reason, List.of("approve_after_edit", "reject", "discard"));
    }

    private static TaskSnapshot snapshot(String status, Pending... pending) {
        TaskSnapshot snap = new TaskSnapshot();
        snap.taskId = "t1";
        snap.status = status;
        snap.pending = List.of(pending);
        snap.outputs = List.of();
        return snap;
    }

    /** The verdicts a run submits (empty when it defers to a human). */
    private static List<ReviewRequest> drive(TaskSnapshot start, List<TaskSnapshot> afterEachReview)
            throws Exception {
        List<ReviewRequest> submitted = new ArrayList<>();
        run(start, afterEachReview, submitted);
        return submitted;
    }

    /** The snapshot a run ends on. */
    private static TaskSnapshot runWith(TaskSnapshot start, List<TaskSnapshot> afterEachReview)
            throws Exception {
        return run(start, afterEachReview, new ArrayList<>());
    }

    /** Wires a runner whose LLM service answers with the given snapshots in order, recording the
     *  verdicts submitted along the way. */
    private static TaskSnapshot run(
            TaskSnapshot start, List<TaskSnapshot> afterEachReview, List<ReviewRequest> submitted)
            throws Exception {
        AgentService agent = mock(AgentService.class);
        SessionService sessions = mock(SessionService.class);

        when(sessions.getCreativeBrief(anyString())).thenReturn(mock(CreativeBrief.class));
        when(agent.startTask(any())).thenReturn(start);
        when(agent.getTaskSnapshot(anyString())).thenReturn(start);
        when(agent.consumeEvents(anyString(), any())).thenReturn(new Thread(() -> { }));
        when(agent.agentConfirmLearning(anyBoolean(), anyString())).thenReturn(null);

        AtomicInteger call = new AtomicInteger();
        when(agent.reviewTask(anyString(), any())).thenAnswer(invocation -> {
            submitted.add(invocation.getArgument(1));
            int i = call.getAndIncrement();
            return afterEachReview.get(Math.min(i, afterEachReview.size() - 1));
        });

        return new NewsroomRunner(agent, sessions).run("s1");
    }

    @Test
    @DisplayName("an ordinary gate is approved")
    void approvesAnOrdinaryGate() throws Exception {
        List<ReviewRequest> submitted = drive(
                snapshot("awaiting_review", ordinary("linkedin")),
                List.of(snapshot("completed")));

        assertThat(submitted).hasSize(1);
        Verdict verdict = submitted.get(0).verdicts().get("linkedin");
        assertThat(verdict.decision()).isEqualTo("approve");
    }

    @Test
    @DisplayName("a compliance-blocked gate gets NO automatic verdict — it is left for a human")
    void leavesABlockedGateOpen() throws Exception {
        // Every way out of a blocked gate is a judgement call: rewrite it, regenerate it knowing
        // what tripped, or give up on the platform. None of those are a machine's to make on the
        // user's behalf — so the runner submits nothing and the gate stays open.
        List<ReviewRequest> submitted = drive(
                snapshot("awaiting_review", blocked("linkedin", "self-harm")),
                List.of(snapshot("completed")));

        assertThat(submitted).isEmpty();
    }

    @Test
    @DisplayName("a blocked run comes back still awaiting review, so a client can act on it")
    void aBlockedRunIsReturnedNotFailed() throws Exception {
        TaskSnapshot result = runWith(
                snapshot("awaiting_review", blocked("linkedin", "self-harm")),
                List.of(snapshot("completed")));

        // Not an exception and not "completed": the run is genuinely mid-decision.
        assertThat(result.status).isEqualTo("awaiting_review");
        assertThat(result.pending).hasSize(1);
        assertThat(result.pending.get(0).allowed_decisions())
                .containsExactly("approve_after_edit", "reject", "discard");
    }

    @Test
    @DisplayName("a mixed gate approves the clean platform and leaves only the blocked one open")
    void handlesEachPlatformOnItsOwnMerits() throws Exception {
        // Partial review: holding the clean platform hostage to the blocked one would be just as
        // wrong as railroading the blocked one through.
        List<ReviewRequest> submitted = drive(
                snapshot("awaiting_review", ordinary("linkedin"), blocked("instagram", "violence")),
                List.of(snapshot("awaiting_review", blocked("instagram", "violence"))));

        Map<String, Verdict> verdicts = submitted.get(0).verdicts();
        assertThat(verdicts).containsOnlyKeys("linkedin");
        assertThat(verdicts.get("linkedin").decision()).isEqualTo("approve");
    }

    @Test
    @DisplayName("a gate that keeps re-opening is abandoned rather than looped on forever")
    void boundsTheReviewLoop() {
        // Without a bound this is an unbounded spend: every lap costs a real re-draft, and nothing
        // upstream stops it because the human verdict that normally paces it has been automated away.
        TaskSnapshot stuck = snapshot("awaiting_review", ordinary("linkedin"));

        assertThat(catchRun(() -> drive(stuck, List.of(stuck))))
                .isNotNull()
                .hasMessageContaining("awaiting review");
    }

    private static Throwable catchRun(ThrowingRunnable body) {
        try {
            body.run();
            return null;
        } catch (Throwable t) {
            return t;
        }
    }

    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}
