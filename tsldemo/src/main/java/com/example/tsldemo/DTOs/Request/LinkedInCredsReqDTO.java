package com.example.tsldemo.DTOs.Request;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInCredsReqDTO(
    @JsonProperty("businessId")
    int businessId,
    @JsonProperty("clientId")
    String clientId,
    @JsonProperty("clientSecret")
    String clientSecret
){}