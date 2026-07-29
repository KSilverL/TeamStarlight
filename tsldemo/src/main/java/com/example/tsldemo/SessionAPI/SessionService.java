package com.example.tsldemo.SessionAPI;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.ApiDTOS;
import com.example.tsldemo.ApiDTOS.*;
import com.example.tsldemo.ApiDTOS.IntakeRequest;
import com.example.tsldemo.ApiDTOS.IntakeResponse;
import com.example.tsldemo.ApiDTOS.IntakeTurnRequest;
import com.example.tsldemo.Business;
import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
import com.example.tsldemo.AgentAPI.AgentService;
import com.example.tsldemo.DTOs.ResponseReceived.IntakeRespDTO;
import com.example.tsldemo.SignInAPI.BusinessRepository;

@Service
public class SessionService {
	@Autowired
	private SessionRepository repo;

	@Autowired
	private BusinessRepository businessRepo;

	private final RestClient restClient;

	@Value("${llm.service.base-url:http://localhost:8080}")
	private String llmServiceBaseUrl;

    public SessionService(RestClient restClient) {
        this.restClient = restClient;
    }
    
    public IntakeResponse sendSessionToAgent(IntakeRequest intakeDTO, int businessId) {
    	Session session = createNewSession(businessId);
        intakeDTO.sessionId = session.getId();
        
        @Nullable 
        IntakeResponse intakeResp = restClient.post()
                .uri(llmServiceBaseUrl + "/intake")
                .contentType(MediaType.APPLICATION_JSON)
                .body(intakeDTO)
                .retrieve()
                .body(IntakeResponse.class);
                
        Message userPrompt = new Message("user", intakeDTO.openingInput);
        Message openingMessage = new Message("assistant",intakeResp.assistantMessage);
        
        session.addMessage(userPrompt);
        session.addMessage(openingMessage);
        
        return intakeResp;
    }
    
    public Session createNewSession(int businessId) {
    	Session session = new Session();
    	
    	if (businessId > 0) {
            Business business = businessRepo.findById(businessId).orElse(null);
            if (business != null) {
                session.setUser(business);
            }
        }
    	
    	repo.save(session);
    	
    	return session;
    }
    
    
    public IntakeResponse getIntakeTurn(IntakeTurnRequest request, String sessionId) {
    	return restClient.post()
                .uri(llmServiceBaseUrl + "/intake/" + sessionId + "/turn")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .body(ApiDTOS.IntakeResponse.class);
    	
    }
    
    //Call once session.isComplete = true;
    public CreativeBrief getCreativeBrief(String sessionId) {
        return restClient.get()
                .uri(llmServiceBaseUrl + "/intake/" + sessionId + "/brief")
                .retrieve()
                .body(CreativeBrief.class);
    }

    
	public void addSession(Session s) {
		repo.save(s);
	}
	
	public List<Session> getSessions() {
		return repo.findAll();
	}

	public List<Session> getSessionsByUser(int businessId) {
		return repo.findByUser_Id(businessId);
	}
	
	public Optional<Session> getSessionBy(String id) {
		return repo.findById(id);
	}

	public void updateSession(String id, Message msg) {
		Session s = repo.getReferenceById(id);
		s.addMessage(msg);
		repo.save(s);
		
	}
	
	public void setSessionTitle(String id, String title) {
		Session s = repo.getReferenceById(id);
		s.setTitle(title);
		repo.save(s);
		
	}
	
	public Session deleteSession(String id) {
    	Session session = repo.findById(id).get();
    	repo.deleteById(id);
    	
    	return session;
    }

}
