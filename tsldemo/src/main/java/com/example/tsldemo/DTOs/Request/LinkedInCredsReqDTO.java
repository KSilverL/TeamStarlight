package com.example.tsldemo.DTOs.Request;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInCredsReqDTO(
    @JsonProperty("clientId")
    String clientId,
    @JsonProperty("clientSecret")
    String clientSecret
){}