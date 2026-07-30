package com.example.tsldemo;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.time.LocalDateTime;

import com.fasterxml.jackson.annotation.JsonIgnore;
import java.util.UUID;
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
	private static boolean complete = false;
	private String title;

	@ElementCollection
	@CollectionTable(name = "session_target_platforms", joinColumns = @JoinColumn(name = "session_id"))
	@Column(name = "platform")
	private List<String> targetPlatforms;

	private String contentTopics;

	@OneToMany(mappedBy = "session", cascade = CascadeType.ALL, orphanRemoval = true)
	@JsonIgnore
	private List<Message> messages = new ArrayList<>();

	@ManyToOne
	@JoinColumn(name = "user_id")
	@JsonIgnore
	private Business user;

	// id comes from the LLM service so both systems share the same session identifier
	public Session() {
		this.id = createSessionID();
		this.status = "running";
		this.createdAt = LocalDateTime.now().toString();
	}

	private String createSessionID() {
		return "intake-"+ UUID.randomUUID().toString().replace("-", "").substring(0, 12);
		
	}
	

	public String getTitle() {
	    return title;
	}
	public void setTitle(String title) {
	    this.title = title;
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

	public List<String> getTargetPlatforms() {
		return targetPlatforms;
	}

	public void setTargetPlatforms(List<String> platforms) {
		this.targetPlatforms = platforms;
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

	public boolean isComplete() {
		return complete;
	}

	public void setComplete(boolean complete) {
		this.complete = complete;
	}
	
}
