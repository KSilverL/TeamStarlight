package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInVideoInitializeUploadRespDTO(
    @JsonProperty("value")
    LinkedInVideoUploadValueDTO value
) {}
