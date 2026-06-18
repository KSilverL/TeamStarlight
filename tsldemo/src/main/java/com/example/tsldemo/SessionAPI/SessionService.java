package com.example.tsldemo.SessionAPI;

import java.util.List;
import java.util.Optional;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.example.tsldemo.Message;
import com.example.tsldemo.Session;

@Service
public class SessionService {
	@Autowired
	private SessionRepository repo;
	
	
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
