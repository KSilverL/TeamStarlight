package com.example.tsldemo.SessionAPI;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import com.example.tsldemo.auth.JwtUtil;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import com.example.tsldemo.ApiDTOS.IntakeRequest;
import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
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

	public SessionController(SessionService service) {
		this.service = service;
	}

	// Must call this first to create a session before any other
	@PostMapping("/api/sessions")
	public IntakeRespDTO addSession(
			@RequestBody IntakeRequest intakeDTO,
			@RequestHeader(value = "Authorization", required = false) String authHeader) {
		
		int businessId = jwtUtil.extractBusinessId(authHeader);
		
		return service.createSession(intakeDTO, businessId);
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
	
	
}
