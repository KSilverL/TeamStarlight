package com.example.tsldemo;

import java.util.List;
import java.util.Map;

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
		@JsonProperty
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
		
		@JsonProperty
		String route;
		
		@JsonProperty("content_types")
		String[] contentTypes;
		
		@JsonProperty("intake_mode")
		String intakeMode;
		
		@JsonProperty("prior_context")
		String priorContext;
		
		@JsonProperty("roundtable_mode")
		String roundtableMode;
	}
	
	public record Pending(String request_id, String platform, String draft, String comment,
            boolean needs_human_intervention) {}
	
	public record Output(String platform, String draft, String decision, String comment,
            boolean needs_human_intervention, List<Map<String,Object>> proposed_rules,
            List<String> content_types,
            String html_card, Map<String,Object> video_storyboard) {}
	
	public record RenderVideo(String platform) {}
	
	//TODO: Move the related api classes to related files to avoid littering this file
	public static class TaskSnapshot {

	    @JsonProperty("task_id")
	    public String taskId;

	    public String status;

	    public Pending[] pending;

	    public Output[] outputs;

	    @JsonProperty("proposed_rules")
	    List<Map<String,Object>> proposedRules;

	    String error;
	    
	}
	
	record Verdict(
			@JsonProperty
			String decision, 
			
			@JsonProperty
			String edited_draft, 
			
			@JsonProperty
			String reason) {}
	
	public record ReviewTaskRequest(
	        Map<String, Verdict> verdicts
	) {}
	
	public record ReviewRequest(@JsonProperty Map<String,Verdict> verdicts) {}
	
	public record ConfirmLearningRequest(Boolean learn) {}
	
	public record ConfirmLearningResponse(
	        @JsonProperty("task_id")
	        String taskId,

	        Boolean learned,

	        @JsonProperty("brand_rules")
	        List<BrandRule> brandRules,

	        @JsonProperty("preference_summary")
	        PreferenceSummary preferenceSummary
	) {}
	
	public record BrandRule(
	        String kind,
	        String rule,
	        String rationale
	) {}
	
	public record PreferenceSummary(
	        @JsonProperty("user_id")
	        String userId,

	        @JsonProperty("business_id")
	        String businessId,

	        @JsonProperty("learned_skills")
	        List<String> learnedSkills,

	        List<String> evidence,

	        @JsonProperty("source_task_id")
	        String sourceTaskId
	) {}
	
	public record TaskSayRequest(
			@JsonProperty("table_id")
			String tableId,
			
			@JsonProperty
			String text,
			
			@JsonProperty
			boolean interrupt
			) {}
	
	public record RaiseHandRequest(
	        @JsonProperty("table_id")
	        String tableId
	) {}
	
	public record SayRequest(
	        @JsonProperty("table_id")
	        String tableId,

	        String text,

	        Boolean interrupt
	) {}
	
	public record RoundControlRequest(
	        @JsonProperty("table_id")
	        String tableId,

	        String action,

	        String text
	) {}
	
	public record RaiseHandResponse(
	        @JsonProperty("task_id")
	        String taskId,

	        @JsonProperty("table_id")
	        String tableId,

	        @JsonProperty("hand_raised")
	        Boolean handRaised
	) {}
	
	public record SayResponse(
	        @JsonProperty("task_id")
	        String taskId,

	        @JsonProperty("table_id")
	        String tableId,

	        Boolean queued,

	        Integer pending
	) {}
	
	public record RoundControlResponse(
	        @JsonProperty("task_id")
	        String taskId,

	        @JsonProperty("table_id")
	        String tableId,

	        String action,

	        Boolean accepted
	) {}
	
}
