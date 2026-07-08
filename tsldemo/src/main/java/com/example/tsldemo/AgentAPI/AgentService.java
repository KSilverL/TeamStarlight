package com.example.tsldemo.AgentAPI;

import java.net.URI;
import java.util.HashMap;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.util.stream.Stream;

import java.net.http.HttpResponse;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;

import com.example.tsldemo.ApiDTOS.*;


@Service
public class AgentService {
	private final RestClient restClient;

	private final HttpClient http = HttpClient.newHttpClient();
	
	@Value("${llm.service.base-url:http://localhost:8080}")
	private String llmServiceBaseUrl;
	
	public AgentService(RestClient restClient) {
        this.restClient = restClient;
    }
	
	private <T> T post(String path, Object request, Class<T> responseType) {
	    return restClient.post()
	            .uri(llmServiceBaseUrl + path)
	            .contentType(MediaType.APPLICATION_JSON)
	            .body(request)
	            .retrieve()
	            .body(responseType);
	}

	
	public Map<String, Object> getAgentTextResponse(Map<String, Object> promptJSON) { 	
    	Map<String, Object> response = restClient.post()
                .uri(llmServiceBaseUrl +"/generate-text")
                .contentType(MediaType.APPLICATION_JSON)
                .body(promptJSON)
                .retrieve()
                .body(Map.class);
    	
    	System.out.println(response);
    	
    	return response;
    }
	
	public Map<String, Object> getAgentVideoResponse(Map<String, Object> promptJSON) { 	
    	Map<String, Object> response = restClient.post()
                .uri(llmServiceBaseUrl +"/generate-video")
                .contentType(MediaType.APPLICATION_JSON)
                .body(promptJSON)
                .retrieve()
                .body(Map.class);
    	
    	System.out.println(response);
    	
    	return response;
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
	
	public SseEmitter streamEvents(String taskId) {
	    SseEmitter emitter = new SseEmitter(Long.MAX_VALUE);

	    new Thread(() -> {

	        try {

	            HttpRequest request = HttpRequest.newBuilder()
	                    .uri(URI.create(
	                        llmServiceBaseUrl 
	                        + "/tasks/" 
	                        + taskId 
	                        + "/events"
	                    ))
	                    .GET()
	                    .build();


	            HttpResponse<Stream<String>> response =
	                    http.send(
	                        request,
	                        HttpResponse.BodyHandlers.ofLines()
	                    );


	            response.body()
	                    .filter(line -> line.startsWith("data: "))
	                    .forEach(line -> {

	                        try {

	                            String json =
	                                line.substring(6);

	                            emitter.send(
	                                SseEmitter.event()
	                                    .data(json)
	                            );

	                        } catch(Exception e) {
	                            emitter.completeWithError(e);
	                        }

	                    });


	            emitter.complete();


	        } catch(Exception e) {
	            emitter.completeWithError(e);
	        }


	    }).start();


	    return emitter;
	}
	
	
}
