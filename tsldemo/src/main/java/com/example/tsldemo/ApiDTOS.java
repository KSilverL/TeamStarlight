package com.example.tsldemo;

import com.fasterxml.jackson.annotation.JsonProperty;

public class ApiDTOS {
	public static class IntakeRequest {

        public String mode;

        @JsonProperty("session_id")
        public String sessionId;

        @JsonProperty("target_platforms")
        public String[] targetPlatforms;

        @JsonProperty("opening_input")
        public String openingInput;

        @JsonProperty("user_id")
        private String userId;

    }
	
	public record IntakeTurnRequest(String user_input) {}
	
	public record IntakeTurnResponse(
	        String reply,
	        String nextPhase,
	        boolean completed
	    ) {}
	
}
