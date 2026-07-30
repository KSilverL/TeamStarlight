package com.example.tsldemo.DTOs.ResponseToFrontEnd;

import com.example.tsldemo.ENUMS.PlatformEnum;
import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class GlobalCredListRespDTO {
    @JsonProperty("businessId")
    Long businessId;

    @JsonProperty("clientId")
    String clientId;

    @JsonProperty("clientSecret")
    String clientSecret;

    @JsonProperty("pageIdArray")
    Long[] pageIdArray;

    @JsonProperty("pageNameArray")
    String[] pageNameArray;

    @JsonProperty("platform")
    PlatformEnum platform;
}
