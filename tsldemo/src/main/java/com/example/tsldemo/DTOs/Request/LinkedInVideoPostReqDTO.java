package com.example.tsldemo.DTOs.Request;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInVideoPostReqDTO(

    @JsonProperty("jobId")
    String jobId,

    @JsonProperty("message")
    String message,

    @JsonProperty("title")
    String title

) {}
