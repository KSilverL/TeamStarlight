package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

public record MetaTokenDetails(
    @JsonProperty("data")
    MetaDataTokenDetails data
) {}
