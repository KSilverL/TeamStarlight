package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInImageUploadValueDTO(
    @JsonProperty("uploadUrl")
    String uploadUrl,

    @JsonProperty("uploadUrlExpiresAt")
    Long uploadUrlExpiresAt,

    @JsonProperty("image")
    String image
) {}
