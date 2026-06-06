package com.example.tsldemo;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;

@Entity
public class Business {
	@Id 
	private int id;
	private String name;
	private String inputData;
	private String username;
	private String password;
	
	
	public Business(int id, String name, String username, String password, String inputData) {
		this.setId(id);
		this.setName(name);
		this.setInputData(inputData);
		this.username = username;
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

	public String getUsername() {
		return username;
	}

	public void setUsername(String username) {
		this.username = username;
	}

	public String getPassword() {
		return password;
	}

	
	
}
