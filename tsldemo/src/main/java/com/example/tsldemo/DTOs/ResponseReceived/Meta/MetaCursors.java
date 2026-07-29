package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

public record MetaCursors(
    
    @JsonProperty("before")
    String before,

    @JsonProperty("after")
    String after

) {}
