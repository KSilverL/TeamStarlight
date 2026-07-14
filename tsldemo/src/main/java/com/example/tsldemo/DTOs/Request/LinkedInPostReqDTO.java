package com.example.tsldemo.DTOs.Request;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInPostReqDTO(

    @JsonProperty("message")
    String message

) {}