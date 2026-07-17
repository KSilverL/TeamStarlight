package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record UploadInstructions(
    @JsonProperty("uploadUrl")
    String uploadUrl,

    @JsonProperty("lastByte")
    Long lastByte,

    @JsonProperty("firstByte")
    Long firstByte
) {}