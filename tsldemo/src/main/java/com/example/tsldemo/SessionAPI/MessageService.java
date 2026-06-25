package com.example.tsldemo.SessionAPI;

import org.springframework.beans.factory.annotation.*;
import org.springframework.stereotype.Service;

import com.example.tsldemo.Message;

@Service
public class MessageService {
	@Autowired
	private MessageRepository repo;
	
	public void addMessage(Message msg) {
		repo.save(msg);
	}
		
}
