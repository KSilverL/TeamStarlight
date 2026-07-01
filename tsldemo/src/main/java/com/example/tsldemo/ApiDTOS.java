package com.example.tsldemo;

import java.util.List;

import com.example.tsldemo.DTOs.Error.Detail;
import com.example.tsldemo.DTOs.ResponseReceived.BriefPartial;
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
	
	public static class IntakeResponse {
		@JsonProperty("intake_mode")
		public String intakeMode;

		@JsonProperty("session_id")
		public String sessionId;

		@JsonProperty("assistant_message")
		public String assistantMessage;

		@JsonProperty("brief_partial")
		public BriefPartial brief_partial;

		@JsonProperty("complete")
		public Boolean complete;

		// ERROR HANDLING
		@JsonProperty("detail")
		public List<Detail> detail;
	}
	
	public record IntakeTurnRequest(String user_input) {}
	
	public record IntakeTurnResponse(
		String sessionId,
			
		@JsonProperty("assistant_message")
	    String assistantMessage,
		    
	    BriefPartial brief_partial,
	    Boolean complete
		    
	) {}
	
}
