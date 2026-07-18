package com.example.tsldemo.DTOs.Request;

import java.time.LocalDateTime;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInPostReqDTO(

    @JsonProperty("message")
    String message,
    
    @JsonProperty("business_id")
    int businessId,
    
    @JsonProperty("scheduled_time")
    LocalDateTime scheduledTime
) {}