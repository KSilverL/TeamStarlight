package com.example.tsldemo.SessionAPI;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import com.example.tsldemo.auth.JwtUtil;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import com.example.tsldemo.ApiDTOS.IntakeRequest;
import com.example.tsldemo.ApiDTOS.IntakeResponse;
import com.example.tsldemo.ApiDTOS.IntakeTurnRequest;
import com.example.tsldemo.ApiDTOS.Output;
import com.example.tsldemo.ApiDTOS.TaskSnapshot;
import com.example.tsldemo.Business;
import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
import com.example.tsldemo.AgentAPI.NewsroomRunner;
import com.example.tsldemo.DTOs.ResponseReceived.IntakeRespDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.FrontIntakeRespDTO;

@RestController
public class SessionController {
	private static class Request {
		public String businessDescription;
		public String brandTone;
		public String[] targetPlatforms;
		public String contentTopics;
		public String contentType;
		public String notes;
		public String userPreferences;
		
		public Request() {}
		
	}
	
	private SessionService service;
	@Autowired
	private MessageService msgServ;
	@Autowired
	private JwtUtil jwtUtil;
	@Value("${llm.service.base-url:http://localhost:8080}")
	private String llmServiceBaseUrl;

	private final NewsroomRunner newsroomRunner;
	
	public SessionController(SessionService service, NewsroomRunner newsroomRunner) {
		this.service = service;
		this.newsroomRunner = newsroomRunner;

	}

	// Must call this first to create a session before any other
	@PostMapping("/api/sessions")
	public IntakeResponse addSession(
			@RequestBody IntakeRequest intakeDTO,
			@RequestHeader(value = "Authorization", required = false) String authHeader) {
		
		int businessId = jwtUtil.extractBusinessId(authHeader);
		
		return service.sendSessionToAgent(intakeDTO, businessId);
	}
	
	
	@GetMapping("/api/sessions")
	public List<Session> getUserSessions(
			@RequestHeader(value = "Authorization", required = false) String authHeader) {
		
		try {
			int businessId = jwtUtil.extractBusinessId(authHeader);
			return service.getSessionsByUser(businessId);
			
		} catch(Exception e) {
			return List.of();
		}
	
	}
	
	
	/**
	 * Names a session, so the sidebar has something to show besides a timestamp.
	 *
	 * The title is worked out by the LLM service and handed to the browser in the POST /tasks
	 * response (and refined over SSE), which left it living in React state and dying on reload
	 * — the column existed, the setter existed, nothing joined them. This is that join.
	 *
	 * Unlike the rest of this controller, it checks the caller: a title is the one part of a
	 * session another business could otherwise rewrite by guessing an id.
	 */
	@PatchMapping("/api/sessions/{id}")
	public ResponseEntity<?> updateSession(
			@PathVariable String id,
			@RequestBody Map<String, String> body,
			@RequestHeader(value = "Authorization", required = false) String authHeader) {

		int businessId = jwtUtil.extractBusinessId(authHeader);
		if (businessId == -1) {
			return ResponseEntity.status(401).body(Map.of("error", "Missing or invalid authorization token"));
		}

		String title = body.get("title");
		// Nothing to do rather than an error: a blank title is the caller having none yet, and
		// writing it would erase a good one.
		if (title == null || title.isBlank()) {
			return ResponseEntity.ok(Map.of("updated", false));
		}

		Optional<Session> found = service.getSessionBy(id);
		if (found.isEmpty()) {
			return ResponseEntity.status(404).body(Map.of("error", "No such session"));
		}
		Business owner = found.get().getUser();
		if (owner == null || owner.getId() != businessId) {
			return ResponseEntity.status(403).body(Map.of("error", "Not your session"));
		}

		service.setSessionTitle(id, title);
		return ResponseEntity.ok(Map.of("updated", true));
	}


	private static class MessageRequest {
		public String role;
		public String content;
	}

	@PostMapping("/api/sessions/{id}/messages")
	public Message addMessages(@PathVariable String id, @RequestBody MessageRequest request) {
		Message msg = new Message(
			request.role != null ? request.role : "user",
			request.content != null ? request.content : ""
		);
		
		service.updateSession(id, msg);
		return msg;
	}
	
	
	@GetMapping("/api/sessions/{id}/messages") 
	public List<Message> getMessages(@PathVariable String id) {
		Session s = service.getSessionBy(id).get();
		return s.getMessages();
		
	}
	
	
	@PostMapping("/intakeTurn/{sessionId}")
	public IntakeResponse addIntakeTurnResponse(
			@PathVariable String sessionId,
            @RequestBody IntakeTurnRequest request) throws Exception {
		
		IntakeResponse response = service.getIntakeTurn(request, sessionId);
		
		Message assistantTurn = new Message("assistant", response.assistantMessage);
		
		Session session = service.getSessionBy(sessionId).get();
		session.setComplete(response.complete);
		
		service.updateSession(sessionId, assistantTurn);
		
		if (response.complete) {
			newsroomRunner.run(sessionId);
		}
        
		return response;
		
	}
	
	@DeleteMapping("api/session/{id}")
	public Session deleteSession(@PathVariable String id) {
		return service.deleteSession(id);
	}
	
}
