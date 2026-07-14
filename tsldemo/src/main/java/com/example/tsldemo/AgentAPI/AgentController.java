package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.example.tsldemo.ApiDTOS.*;
import com.example.tsldemo.ApiDTOS.CreativeBrief;
import com.example.tsldemo.ApiDTOS.ReviewRequest;
import com.example.tsldemo.ApiDTOS.TaskSnapshot;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;


@RestController
public class AgentController {
	@Autowired
	private AgentService service;
	
	@PostMapping("/generate-text")
	public String extractAssistantTextResponse(@RequestBody String prompt) {
		System.out.println(prompt);
		ObjectMapper objMap = new ObjectMapper();
		
		Map<String, Object> promptJSON = objMap.readValue(prompt, new TypeReference<Map<String, Object>>() {});
		
		Map<String, Object> response = service.getAgentTextResponse(promptJSON);
		
		return objMap.writeValueAsString(response);
		
	}
	

	@PostMapping("/generate-video") 
	public String extractAssistantVideoResponse(@RequestBody String prompt) {
		System.out.println(prompt);
		
		ObjectMapper objMap = new ObjectMapper();
		Map<String, Object> promptJSON = objMap.readValue(prompt, new TypeReference<Map<String, Object>>() {});
		
		Map<String, Object> videoResponse = service.getAgentVideoResponse(promptJSON);
		
		return objMap.writeValueAsString(videoResponse);
		
	}
	
	@PostMapping("/tasks") 
	public TaskSnapshot sendCreativeBrief(@RequestBody CreativeBrief brief) {
		return service.startTask(brief);
	}
	
	
	@PostMapping("/{taskId}/review")
    public TaskSnapshot submitReview(@PathVariable String taskId, @RequestBody ReviewRequest request) {
        return service.reviewTask(taskId, request);
    }

    @PostMapping("/{taskId}/confirm-learning")
    public ConfirmLearningResponse confirmLearning(
            @PathVariable String taskId,
            @RequestBody ConfirmLearningRequest request) {
        return service.agentConfirmLearning(request.learn(), taskId);
    }

    @GetMapping("/{taskId}")
    public TaskSnapshot getTaskSnapshot(@PathVariable String taskId) {
        return service.getTaskSnapshot(taskId);
    }

    @PostMapping("/{taskId}/raise-hand")
    public RaiseHandResponse raiseHand(
            @PathVariable String taskId,
            @RequestBody RaiseHandRequest request) {
        return service.agentRaiseHand(taskId, request.tableId());
    }

    @PostMapping("/{taskId}/say")
    public SayResponse say(
            @PathVariable String taskId,
            @RequestBody SayRequest request) {
        return service.agentSay(taskId, request);
    }

    @PostMapping("/{taskId}/round-control")
    public RoundControlResponse roundControl(
            @PathVariable String taskId,
            @RequestBody RoundControlRequest request) {
        return service.agentRoundControl(taskId, request);
    }
	
//    @GetMapping(value="/tasks/{taskId}/events",produces = MediaType.TEXT_EVENT_STREAM_VALUE)
//    public SseEmitter streamEvents(@PathVariable String taskId) {
//    	return service.consumeEvents(taskId);
//    	    
//    }
	
}

