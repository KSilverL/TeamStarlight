package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonProperty;

public record IniMediaValue(
    @JsonProperty("uploadUrlExpiresAt")
    Long uploadUrlExpiresAt,

    @JsonProperty("uploadUrl")
    String uploadUrl,

    @JsonProperty("mediaUrn")
    @JsonAlias({"image", "video"})
    String mediaUrn,

    @JsonProperty("uploadInstructions")
    UploadInstructions uploadInstructions,

    @JsonProperty("uploadToken")
    String uploadToken
) {}