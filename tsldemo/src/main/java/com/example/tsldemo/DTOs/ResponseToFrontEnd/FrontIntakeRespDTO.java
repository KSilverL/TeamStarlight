package com.example.tsldemo.DTOs.ResponseToFrontEnd;

import com.fasterxml.jackson.annotation.JsonProperty;

public record FrontIntakeRespDTO(
    @JsonProperty("assistant_message")
    String assistantMessage,

    @JsonProperty("target_platforms")
    String targetPlatforms
) {}
