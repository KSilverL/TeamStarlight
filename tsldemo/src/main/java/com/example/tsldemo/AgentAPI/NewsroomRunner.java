package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

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

	    while ("running".equals(task.status)) {
	        Thread.sleep(200);
	        task = agentServ.getTaskSnapshot(taskId);
	    }

	    if ("error".equals(task.status)) {
	        throw new RuntimeException("Task failed: " + task.error);
	    }

	    while ("awaiting_review".equals(task.status)) {
	        Map<String, Verdict> verdicts = new HashMap<>();
	        for (Pending pending : task.pending) {
	            verdicts.put(pending.platform(), new Verdict("approve", null, null));
	        }
	        task = agentServ.reviewTask(taskId, new ReviewRequest(verdicts));
	    }

	    agentServ.agentConfirmLearning(true, taskId);
	    return task;
	    
	}
	
}
