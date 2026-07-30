package com.example.tsldemo;

import java.util.List;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;

@Entity
@Table
public class Business {
	@Id 
	@GeneratedValue(strategy = GenerationType.AUTO)
	private int id;
	private String name;
	private String inputData;
	private String email;
	private String password;
	
	@OneToMany(mappedBy = "user", cascade = CascadeType.ALL, orphanRemoval = true)
	private List<Session> sessions;
	
	public Business() {}
	
	public Business(String name, String email, String password, String inputData) {
		this.setName(name);
		this.setInputData(inputData);
		this.setEmail(email);
		this.password = password;
		
	}

	public int getId() {
		return id;
	}

	public void setId(int id) {
		this.id = id;
	}

	public String getName() {
		return name;
	}

	public void setName(String name) {
		this.name = name;
	}

	public String getInputData() {
		return inputData;
	}

	public void setInputData(String inputData) {
		this.inputData = inputData;
	}



	public String getPassword() {
		return password;
	}
	
	@Override
	public String toString() {
		return String.format(
			    "Account created: ID=%d, Name=%s, Username=%s",
			    this.getId(),
			    this.getName(),
			    this.getEmail()
			);
	}

	public String getEmail() {
		return email;
	}

	public void setEmail(String email) {
		this.email = email;
	}
	
	public void addSession(Session s) {
		sessions.add(s);
		s.setUser(this);
	}
}