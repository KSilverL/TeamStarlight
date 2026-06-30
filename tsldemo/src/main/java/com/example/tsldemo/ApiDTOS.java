package com.example.tsldemo;

public class ApiDTOS {
	public record IntakeTurnRequest(String user_input) {}
	
	public record IntakeTurnResponse(
	        String reply,
	        String nextPhase,
	        boolean completed
	    ) {}
	
}
