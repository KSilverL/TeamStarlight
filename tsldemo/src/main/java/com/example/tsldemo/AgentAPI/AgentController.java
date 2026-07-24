package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
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
	
	@PostMapping("/text")
    public GenerateTextResponse generateText(@RequestBody GenerateTextRequest request) {
        return service.generateText(request);
    }

    @PostMapping("/brand-card")
    public GenerateHtmlResponse generateHtmlCard(@RequestBody GenerateHtmlRequest request) {
        return service.generateHtmlCard(request);
    }

    @PostMapping("/tasks/{taskId}/render-video")
    public RenderVideoResponse renderVideo(
            @PathVariable String taskId,
            @RequestBody RenderVideoRequest request) {
        return service.renderVideo(taskId, request.platform());
    }

    @GetMapping("/video-jobs/{jobId}")
    public VideoJobResponse getVideoJob(@PathVariable String jobId) {
        return service.getVideoJob(jobId);
    }

    @GetMapping(value = "/video-jobs/{jobId}/download", produces = "video/mp4")
    public ResponseEntity<byte[]> downloadVideo(@PathVariable String jobId) {
        byte[] video = service.downloadVideo(jobId);
        return ResponseEntity.ok()
                .contentType(MediaType.valueOf("video/mp4"))
                .body(video);
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

    @GetMapping(
    	    value = "/tasks/{taskId}/events",
    	    produces = MediaType.TEXT_EVENT_STREAM_VALUE
    	)
    	public SseEmitter events(@PathVariable String taskId) {

    	    SseEmitter emitter = new SseEmitter(Long.MAX_VALUE);

    	    service.consumeEvents(taskId, event -> {
    	        try {
    	            emitter.send(
    	                SseEmitter.event()
    	                    .name("message")
    	                    .data(event)
    	            );
    	        } catch (Exception e) {
    	            emitter.completeWithError(e);
    	        }
    	    });

    	    return emitter;
    	}
	
}

