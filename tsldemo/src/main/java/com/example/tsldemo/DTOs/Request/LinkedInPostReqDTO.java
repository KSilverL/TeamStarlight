package com.example.tsldemo.DTOs.Request;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInPostReqDTO(

    @JsonProperty("businessId")
    String businessId,

    @JsonProperty("message")
    String message

) {}