package com.example.tsldemo.DTOs.ResponseReceived;

import com.fasterxml.jackson.annotation.JsonProperty;

public record BriefPartial(
    @JsonProperty("target_platforms")
    String[] targetPlatforms,

    @JsonProperty("topic")
    String topic
) {}
