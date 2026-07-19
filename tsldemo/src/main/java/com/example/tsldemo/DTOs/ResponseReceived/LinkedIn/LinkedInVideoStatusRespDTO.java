package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInVideoStatusRespDTO(
    @JsonProperty("id")
    String id,

    @JsonProperty("status")
    String status,

    @JsonProperty("processingFailureReason")
    String processingFailureReason
) {}
