package com.example.tsldemo.SessionAPI;

import java.util.List;
import java.util.Optional;


import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import com.example.tsldemo.Message;
import com.example.tsldemo.Session;

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
	
	
	public SessionController(SessionService service) {
		this.service = service;
	}
	

	@PostMapping("/api/sessions") 
	public String addSession(@RequestBody Request request) {
		Session s = new Session();
		s.setTargetPlatforms(request.targetPlatforms);
		service.addSession(s);
		
		return s.toString();
		
	}
	
	@GetMapping("/api/sessions")
	public List<Session> getAllSessions() {
		return service.getSessions();
	}
	
	
	@PostMapping("/api/sessions/{id}/messages") 
	public Message addMessages(@PathVariable String id, @RequestBody String content) {
		int sIndex = content.indexOf(":") + 1;
		int eIndex = content.lastIndexOf("}");
		String cleanedMessage = content.substring(sIndex, eIndex);
		
		Message msg = new Message("user", cleanedMessage);
		
		service.updateSession(id, msg);
				
		return msg;
		
	}
	
	@GetMapping("/api/sessions/{id}/messages") 
	public List<Message> getMessages(@PathVariable String id) {
		Session s = service.getSessionBy(id).get();
		return s.getMessages();
		
	}
	
}
