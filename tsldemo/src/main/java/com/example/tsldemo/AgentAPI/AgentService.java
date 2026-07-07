package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.ApiDTOS.ConfirmLearningResponse;
import com.example.tsldemo.ApiDTOS.CreativeBrief;
import com.example.tsldemo.ApiDTOS.RaiseHandRequest;
import com.example.tsldemo.ApiDTOS.RaiseHandResponse;
import com.example.tsldemo.ApiDTOS.ReviewRequest;
import com.example.tsldemo.ApiDTOS.SayRequest;
import com.example.tsldemo.ApiDTOS.SayResponse;
import com.example.tsldemo.ApiDTOS.TaskSayRequest;
import com.example.tsldemo.ApiDTOS.*;


@Service
public class AgentService {
	private final RestClient restClient;

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
	
	public TaskSnapshot getCurrentTaskStatus(CreativeBrief brief) {
		return restClient.post()
                .uri(llmServiceBaseUrl + "/tasks")
                .contentType(MediaType.APPLICATION_JSON)
                .body(brief)
                .retrieve()
                .body(TaskSnapshot.class);
	}
	
	public TaskSnapshot reviewTask(String taskId, ReviewTaskRequest request) {
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
	
	
}
