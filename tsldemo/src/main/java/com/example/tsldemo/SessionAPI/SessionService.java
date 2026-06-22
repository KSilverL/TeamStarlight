package com.example.tsldemo.SessionAPI;

import java.util.List;
import java.util.Optional;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
import com.example.tsldemo.DTOs.Request.IntakeReqDTO;
import com.example.tsldemo.DTOs.ResponseReceived.IntakeRespDTO;

@Service
public class SessionService {
	@Autowired
	private SessionRepository repo;
	
	private final RestClient restClient;

    public SessionService(RestClient restClient) {
        this.restClient = restClient;
    }
	
	public IntakeRespDTO createSession(IntakeReqDTO intakeDTO) {

        IntakeRespDTO intakeResp = restClient.post()
                .uri("http://localhost:8080/intake")
				.contentType(MediaType.APPLICATION_JSON)
				.body(intakeDTO)
                .retrieve()
                .body(IntakeRespDTO.class);
		return intakeResp;
    }

	public void addSession(Session s) {
		repo.save(s);
	}
	
	public List<Session> getSessions() {
		return repo.findAll();
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
