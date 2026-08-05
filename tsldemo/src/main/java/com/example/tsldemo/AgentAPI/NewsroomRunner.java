package com.example.tsldemo.AgentAPI;

import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import com.example.tsldemo.ApiDTOS.*;
import com.example.tsldemo.SessionAPI.SessionService;

/**
 * Drives one newsroom run WITHOUT a human — the unattended/demo path.
 *
 * It approves ordinary gates, and that is the whole of its authority. A gate the compliance screen
 * BLOCKED is left open for a person, because none of the three ways out of one belong to a machine:
 * `approve_after_edit` needs someone to write the edit, `reject` regenerates unbounded (with no
 * human verdict between laps, which is the only thing pacing that loop), and `discard` throws the
 * platform away on the user's behalf without asking. Plain `approve` is not even offered — the
 * service answers 400, since it is absent from the gate's `allowed_decisions`.
 *
 * So on a block this returns EARLY with the task still `awaiting_review`. That is the intended
 * outcome, not a failure: the pending entries carry `blocked` / `block_reason` /
 * `allowed_decisions`, and a human client presents those three choices and submits the verdict.
 */
@Component
public class NewsroomRunner {
	private final AgentService agentServ;
    private final SessionService sessionServ;

    /** How long to wait on the event stream before re-checking the snapshot anyway.
     *
     *  The SSE thread is fire-and-forget: a connection error kills it and nothing else notices. An
     *  unbounded take() on a queue nobody will ever write to again parks the calling thread — an
     *  HTTP worker thread — forever. Polling instead makes the snapshot the source of truth and the
     *  stream merely a way to react sooner. */
    private static final Duration EVENT_WAIT = Duration.ofSeconds(5);

    /** Total budget for reaching a terminal state, so no failure mode can hang the caller. */
    private static final Duration RUN_DEADLINE = Duration.ofMinutes(15);

    /** Belt-and-braces bound on the gate loop. Each pass costs real LLM work, so a run that keeps
     *  bouncing back to `awaiting_review` must stop rather than bill indefinitely. */
    private static final int MAX_REVIEW_ROUNDS = 10;

    public NewsroomRunner(AgentService agentServ, SessionService sessionServ) {
        this.agentServ = agentServ;
        this.sessionServ = sessionServ;
    }

    /**
     * Start a run and let it finish on its own thread — the form a web request should use.
     *
     * A failure is logged rather than thrown: there is no caller left to catch it, and the run's
     * own state is already visible through `GET /tasks/{id}` and the event stream, which is where
     * anyone watching will see it.
     */
    @Async("newsroomExecutor")
    public void runAsync(String sessionId) {
        try {
            run(sessionId);
        } catch (Exception e) {
            System.err.println("[run] session " + sessionId + " failed: " + e);
            e.printStackTrace();
        }
    }

	// Called once, after intake is confirmed complete
    public TaskSnapshot run(String sessionId) throws Exception {
        CreativeBrief brief = sessionServ.getCreativeBrief(sessionId);
        TaskSnapshot task = agentServ.startTask(brief);
        String taskId = task.taskId;

        System.out.println("[run] started task " + taskId + " status=" + task.status);

        BlockingQueue<Map<String, Object>> events = new LinkedBlockingQueue<>();
        agentServ.consumeEvents(taskId, ev -> {
            System.out.println("[event] " + ev);
            events.offer(ev);
        });

        long deadline = System.nanoTime() + RUN_DEADLINE.toNanos();

        // Wait for the first sign that status left "running". The poll is what makes this safe: if
        // the SSE thread has died, we still re-check the snapshot every EVENT_WAIT.
        while ("running".equals(task.status)) {
            if (System.nanoTime() > deadline) {
                throw new RuntimeException("Task " + taskId + " still running after " + RUN_DEADLINE);
            }
            events.poll(EVENT_WAIT.toMillis(), TimeUnit.MILLISECONDS);
            task = agentServ.getTaskSnapshot(taskId);
            System.out.println("[run] re-checked status=" + task.status);
        }

        if ("error".equals(task.status)) {
            throw new RuntimeException("Task failed: " + task.error);
        }

        int round = 0;
        while ("awaiting_review".equals(task.status)) {
            if (++round > MAX_REVIEW_ROUNDS) {
                throw new RuntimeException(
                        "Task " + taskId + " still awaiting review after " + MAX_REVIEW_ROUNDS
                        + " rounds — abandoning rather than looping");
            }
            if (System.nanoTime() > deadline) {
                throw new RuntimeException("Task " + taskId + " unresolved after " + RUN_DEADLINE);
            }

            Map<String, Verdict> verdicts = new HashMap<>();
            List<String> awaitingAHuman = new ArrayList<>();
            for (Pending pending : task.pending) {
                if (pending.blocked()) {
                    awaitingAHuman.add(pending.platform());
                } else {
                    verdicts.put(pending.platform(), new Verdict("approve", null, null));
                }
            }

            if (verdicts.isEmpty()) {
                // Everything still open is compliance-blocked, and none of the three ways out
                // are this runner's to take (see the note on `awaitingAHuman` below). Stop and
                // leave the gates open — the task stays `awaiting_review` on purpose.
                System.out.println("[run] leaving blocked platforms " + awaitingAHuman
                        + " open for a human decision");
                return task;
            }

            // Partial review: the service resumes only the request_ids it gets verdicts for and
            // leaves the rest pending, so approving the clean platforms does not railroad the
            // blocked ones. The next pass sees only blocked gates and returns above.
            System.out.println("[run] submitting review for platforms=" + verdicts.keySet());
            task = agentServ.reviewTask(taskId, new ReviewRequest(verdicts));
            System.out.println("[run] after review status=" + task.status);
        }

        agentServ.agentConfirmLearning(true, taskId);
        System.out.println("[run] done, outputs=" + task.outputs);
        return task;
    }

}
