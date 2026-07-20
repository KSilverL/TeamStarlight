package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInVideoUploadValueDTO(
    @JsonProperty("video")
    String video,

    @JsonProperty("uploadToken")
    String uploadToken,

    @JsonProperty("uploadInstructions")
    List<LinkedInVideoUploadInstructionDTO> uploadInstructions,

    @JsonProperty("uploadUrlsExpireAt")
    Long uploadUrlsExpireAt
) {}
