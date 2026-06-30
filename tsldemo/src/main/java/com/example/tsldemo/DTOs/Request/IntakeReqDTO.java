package com.example.tsldemo.DTOs.Request;

import com.fasterxml.jackson.annotation.JsonProperty;

public record IntakeReqDTO(
    @JsonProperty("mode")
    String mode,

    @JsonProperty("opening_input")
    String openingInput
) {}
