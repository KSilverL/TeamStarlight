package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import com.example.tsldemo.ApiDTOS.*;
import com.example.tsldemo.SessionAPI.SessionService;

@Component
public class NewsroomRunner {
	private final AgentService agentServ;
    private final SessionService sessionServ;

    public NewsroomRunner(AgentService agentServ, SessionService sessionServ) {
        this.agentServ = agentServ;
        this.sessionServ = sessionServ;
    }
    
	// Called once, after intake is confirmed complete
    public TaskSnapshot run(String sessionId) throws Exception {
        CreativeBrief brief = sessionServ.getCreativeBrief(sessionId);
        TaskSnapshot task = agentServ.startTask(brief);
        String taskId = task.taskId;

        System.out.println("[run] started task " + taskId + " status=" + task.status);

        BlockingQueue<Map<String, Object>> events = new LinkedBlockingQueue<>();
        Thread sseThread = agentServ.consumeEvents(taskId, ev -> {
            System.out.println("[event] " + ev);
            events.offer(ev);
        });

        // Wait for the first sign that status left "running"
        while ("running".equals(task.status)) {
            events.take();
            task = agentServ.getTaskSnapshot(taskId);
            System.out.println("[run] re-checked status=" + task.status);
        }
        // no more sseThread.interrupt() — let it close naturally when the server ends the stream

        if ("error".equals(task.status)) {
            throw new RuntimeException("Task failed: " + task.error);
        }

        while ("awaiting_review".equals(task.status)) {
            Map<String, Verdict> verdicts = new HashMap<>();
            for (Pending pending : task.pending) {
                verdicts.put(pending.platform(), new Verdict("approve", null, null));
            }
            System.out.println("[run] submitting review for platforms=" + verdicts.keySet());
            task = agentServ.reviewTask(taskId, new ReviewRequest(verdicts));
            System.out.println("[run] after review status=" + task.status);
        }

        agentServ.agentConfirmLearning(true, taskId);
        System.out.println("[run] done, outputs=" + task.outputs);
        return task;
    }
	
}
