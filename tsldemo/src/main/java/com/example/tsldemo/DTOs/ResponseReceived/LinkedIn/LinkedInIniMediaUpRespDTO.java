package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInIniMediaUpRespDTO(
    @JsonProperty("value")
    IniMediaValue value
) {}
