package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

@Service
public class AgentService {
	private final RestClient restClient;

	@Value("${llm.service.base-url:http://localhost:8080}")
	private String llmServiceBaseUrl;
	
	public AgentService(RestClient restClient) {
        this.restClient = restClient;
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
	
}
