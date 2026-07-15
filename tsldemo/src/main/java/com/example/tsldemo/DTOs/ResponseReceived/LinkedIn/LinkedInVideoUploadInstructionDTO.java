package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInVideoUploadInstructionDTO(
    @JsonProperty("uploadUrl")
    String uploadUrl,

    @JsonProperty("firstByte")
    long firstByte,

    @JsonProperty("lastByte")
    long lastByte
) {}
