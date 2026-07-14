package com.example.tsldemo.SessionAPI;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.Business;
import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
import com.example.tsldemo.DTOs.Request.IntakeReqDTO;
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
    
    //TODO: clean function
    public IntakeRespDTO createSession(IntakeReqDTO intakeDTO, int businessId) {
    	Session session = new Session();
        String sessionId = session.getId();
        
        repo.save(session);
        
        Map<String, Object> body = new HashMap<>();
        body.put("session_id", sessionId);
        body.put("opening_user_input", intakeDTO.openingInput());
        body.put("mode", "text"); 
      
        //TODO: Fix IntakeReqDTO
        IntakeRespDTO intakeResp = restClient.post()
                .uri(llmServiceBaseUrl + "/intake")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(IntakeRespDTO.class);
                
        Message userPrompt = new Message("user", intakeDTO.openingInput());
        Message openingMessage = new Message("assistant",intakeResp.assistantMessage());
        
        session.addMessage(userPrompt);
        session.addMessage(openingMessage);

        if (businessId > 0) {
            Business business = businessRepo.findById(businessId).orElse(null);
            if (business != null) {
                session.setUser(business);
            }
        }
        
        return intakeResp;
    }
    
    public Session deleteSession(String id) {
    	Session session = repo.findById(id).get();
    	repo.deleteById(id);
    	
    	return session;
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

	public String updateSession(String id, Message msg) {
		Session s = repo.getReferenceById(id);
		s.addMessage(msg);
		repo.save(s);
		
		return null;
	}
	
}
