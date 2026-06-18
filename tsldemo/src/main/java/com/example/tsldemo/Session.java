package com.example.tsldemo;

import java.util.List;
import java.util.Random;
import java.time.LocalDateTime;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.persistence.*;

@Entity
@Table
public class Session {
	
	@Id
	private String id;
	private String createdAt;
	private String updatedAt;
	private String status;
	private String phase;
	private String[] targetPlatforms;
	private String contentTopics;
	
	@OneToMany(mappedBy = "session", cascade = CascadeType.ALL, orphanRemoval = true)
	private List<Message> messages;
	
	@ManyToOne
	@JoinTable(name = "user_id")
	@JsonIgnore
	private Business user;
	
	public Session() {
		this.id = createId();
		this.status = "running"; //default setting
		this.createdAt = LocalDateTime.now().toString();
	}
	
	private String createId() {
		Random rand = new Random();
		int intId = rand.nextInt();
		String hexId = Integer.toHexString(intId);
		
		return "sess-" + hexId;
	}

//	@JsonProperty("userId")
//	public int getUserId() {
//		return user.getId();
//	}
	
	public String getId() {
		return this.id;
	}
	
	public String getCreatedAt() {
		return createdAt;
	}

	public void setCreatedAt(String createdAt) {
		this.createdAt = createdAt;
	}

	public String getUpdatedAt() {
		return updatedAt;
	}

	public void setUpdatedAt(String updatedAt) {
		this.updatedAt = updatedAt;
	}

	public String getStatus() {
		return status;
	}

	public void setStatus(String status) {
		this.status = status;
	}

	public String getPhase() {
		return phase;
	}

	public void setPhase(String phase) {
		this.phase = phase;
	}

	public String[] getTargetPlatforms() {
		return targetPlatforms;
	}

	public void setTargetPlatforms(String[] strings) {
		this.targetPlatforms = strings;
	}

	public String getContentTopics() {
		return contentTopics;
	}

	public void setContentTopics(String contentTopics) {
		this.contentTopics = contentTopics;
	}
	
	public void addMessage(Message msg) {
		messages.add(msg);
		msg.setSession(this);
	}
	
	public List<Message> getMessages() {
		return messages;
	}
	
	public void setUser(Business b) {
		this.user = b;
	}
	
}
