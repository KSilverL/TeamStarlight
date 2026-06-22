package com.example.tsldemo.DTOs.ResponseReceived;

import java.util.List;

import com.example.tsldemo.DTOs.Error.Detail;
import com.fasterxml.jackson.annotation.JsonProperty;

public record IntakeRespDTO(
    @JsonProperty("intake_mode")
	String intakeMode,

    @JsonProperty("session_id")
	String sessionId,

    @JsonProperty("assistant_message")
    String assistantMessage,

    @JsonProperty("brief_partial")
    BriefPartial brief_partial,

    @JsonProperty("complete")
    Boolean complete,

    // ERROR HANDLING
    @JsonProperty("detail")
    List<Detail> detail
) {}