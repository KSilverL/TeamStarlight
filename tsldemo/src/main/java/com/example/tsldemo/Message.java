package com.example.tsldemo;

import java.time.LocalDateTime;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.persistence.*;


@Entity
@Table
public class Message {
	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	@JsonProperty("messageId")
	private Long id;
	@JsonProperty
	private String role;
	@JsonProperty
	private String variant;
	@JsonProperty
	private String content;
	@JsonProperty
	private String timestamp;
	
	@ManyToOne
	@JoinColumn(name = "session_id")
	@JsonIgnore
	private Session session;
	
	public Message(String role, String content) {
		this.timestamp = LocalDateTime.now().toString();
		this.role = role;
		this.content = content;

	}
	
	public Message() {}
	
	@JsonProperty("sessionId")
	public String getSessionId() {
		return session.getId();
	}

	public String getRole() {
		return role;
	}
	
	public void setRole(String role) {
		this.role = role;
	}
	
	public String getVariant() {
		return variant;
	}
	
	public void setVariant(String variant) {
		this.variant = variant;
	}
	
	public String getContent() {
		return content;
	}
	
	public String getTimestamp() {
		return timestamp;
	}
	
	public Session getSession() {
		return session;
	}
	
	
	public void setSession(Session session) {
		this.session = session;
	}
	
}
