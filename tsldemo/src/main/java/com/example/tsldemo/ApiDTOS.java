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
        
        @JsonProperty("prior_context")
        private String priorContext;

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
	
	public static class CreativeBrief {
		String topic;
		
		@JsonProperty("target_platforms")
		String[] targetPlatforms;

		@JsonProperty("user_intent")
		String userIntent;
		
		@JsonProperty("tone_hint")
		String toneHint;
		
		@JsonProperty("business_id")
		String businessId;
		
		@JsonProperty("user_id")
		String userId;
		
		String route;
		
		@JsonProperty("intake_mode")
		String intakeMode;
		
		@JsonProperty("prior_context")
		String priorContext;
		
	}
	
	//TODO: Move the related api classes to related files to avoid littering this file
	public static class TaskStatus {

	    @JsonProperty("task_id")
	    public String taskId;

	    public String status;

	    public PendingItem[] pending;

	    public OutputItem[] outputs;

	    @JsonProperty("proposed_rules")
	    public ProposedRule[] proposedRules;

	    public static class PendingItem {
	        @JsonProperty("request_id")
	        public String requestId;

	        public String platform;
	        public String draft;
	        public String comment;

	        @JsonProperty("needs_human_intervention")
	        public boolean needsHumanIntervention;
	    }

	    public static class OutputItem {
	        public String platform;
	        public String draft;
	        public String decision;
	        public String comment;

	        @JsonProperty("needs_human_intervention")
	        public boolean needsHumanIntervention;

	        @JsonProperty("proposed_rules")
	        public ProposedRule[] proposedRules;

	        @JsonProperty("content_types")
	        public String[] contentTypes;

	        @JsonProperty("html_card")
	        public String htmlCard;

	        @JsonProperty("video_storyboard")
	        public VideoStoryboard videoStoryboard;
	    }

	    public static class VideoStoryboard {
	        @JsonProperty("brandName")
	        public String brandName;

	        public Slide[] slides;
	    }

	    public static class Slide {
	        @JsonProperty("type")
	        public String type;

	        @JsonProperty("content")
	        public Object content;
	    }

	    public static class ProposedRule {
	        public String kind;
	        public String rule;
	        public String rationale;
	    }
	}

	
}
