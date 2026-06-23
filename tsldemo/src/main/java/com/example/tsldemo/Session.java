package com.example.tsldemo;

import java.util.ArrayList;
import java.util.List;
import java.time.LocalDateTime;

import com.fasterxml.jackson.annotation.JsonIgnore;

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

	@ElementCollection
	@CollectionTable(name = "session_target_platforms", joinColumns = @JoinColumn(name = "session_id"))
	@Column(name = "platform")
	private List<String> targetPlatforms;

	private String contentTopics;

	@OneToMany(mappedBy = "session", cascade = CascadeType.ALL, orphanRemoval = true)
	private List<Message> messages = new ArrayList<>();

	@ManyToOne
	@JoinColumn(name = "user_id")
	@JsonIgnore
	private Business user;

	// id comes from the LLM service so both systems share the same session identifier
	public Session(String id) {
		this.id = id;
		this.status = "running";
		this.createdAt = LocalDateTime.now().toString();
	}

	public Session() {}

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
	
}
