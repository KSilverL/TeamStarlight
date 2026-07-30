package com.example.tsldemo.DTOs.Request.GlobalCrossPlatform;

import com.example.tsldemo.ENUMS.PlatformEnum;
import com.fasterxml.jackson.annotation.JsonProperty;

public record GlobalCredsReqDTO(
    
    @JsonProperty("businessId")
    Long businessId,
    
    @JsonProperty("clientId")
    String clientId,
    
    @JsonProperty("clientSecret")
    String clientSecret,

    @JsonProperty("platform")
    PlatformEnum platform

) {}
