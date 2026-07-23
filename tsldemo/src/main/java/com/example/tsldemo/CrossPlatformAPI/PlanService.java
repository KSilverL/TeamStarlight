package com.example.tsldemo.CrossPlatformAPI;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

@Service
public class PlanService {

    private final RestClient restClient;

    @Value("${llm.service.base-url:http://localhost:8080}")
    private String llmServiceBaseUrl;

    public PlanService(RestClient restClient) {
        this.restClient = restClient;
    }

 
    @SuppressWarnings("unchecked")
    public Map<String, Object> createPlan(int businessId, Map<String, Object> body) {
        body.put("business_id", String.valueOf(businessId)); 

        return restClient.post()
                .uri(llmServiceBaseUrl + "/plans")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(Map.class);
    }

  
    @SuppressWarnings("unchecked")
    public Map<String, Object> listPlans(int businessId, String status) {
        String uri = llmServiceBaseUrl + "/plans?business_id=" + businessId
                + (status != null && !status.isBlank() ? "&status=" + status : "");

        return restClient.get()
                .uri(uri)
                .retrieve()
                .body(Map.class);
    }

   
    @SuppressWarnings("unchecked")
    public Map<String, Object> getPlan(String planId) {
        return restClient.get()
                .uri(llmServiceBaseUrl + "/plans/" + planId)
                .retrieve()
                .body(Map.class);
    }

    
    @SuppressWarnings("unchecked")
    public Map<String, Object> confirmPlan(String planId) {
        return restClient.post()
                .uri(llmServiceBaseUrl + "/plans/" + planId + "/confirm")
                .retrieve()
                .body(Map.class);
    }

    
    @SuppressWarnings("unchecked")
    public Map<String, Object> patchPlanItem(String planId, String itemId, Map<String, Object> body) {
        return restClient.patch()
                .uri(llmServiceBaseUrl + "/plans/" + planId + "/items/" + itemId)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(Map.class);
    }

    
    @SuppressWarnings("unchecked")
    public Map<String, Object> executePlanItem(String planId, String itemId, Map<String, Object> body) {
        return restClient.post()
                .uri(llmServiceBaseUrl + "/plans/" + planId + "/items/" + itemId + "/execute")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body != null ? body : Map.of())
                .retrieve()
                .body(Map.class);
    }

    
    @SuppressWarnings("unchecked")
    public Map<String, Object> getDuePlans(String date, Integer businessId) {
        String uri = llmServiceBaseUrl + "/plans/due?date=" + date
                + (businessId != null ? "&business_id=" + businessId : "");

        return restClient.get()
                .uri(uri)
                .retrieve()
                .body(Map.class);
    }
    
    @SuppressWarnings("unchecked")
    public Map<String,Object> getTask(String taskId){

        return restClient.get()
                .uri(llmServiceBaseUrl + "/tasks/" + taskId)
                .retrieve()
                .body(Map.class);
    }
    
    @SuppressWarnings("unchecked")
    public Map<String, Object> clarifyPlan(int businessId, Map<String, Object> body) {
        body.put("business_id", String.valueOf(businessId));

        return restClient.post()
                .uri(llmServiceBaseUrl + "/plans/clarify")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(Map.class);
    }
    
    @SuppressWarnings("unchecked")
    public Map<String, Object> refinePlan(String planId,
                                          Map<String,Object> body) {

        return restClient.post()
                .uri(llmServiceBaseUrl + "/plans/" + planId + "/refine")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(Map.class);
    }
}