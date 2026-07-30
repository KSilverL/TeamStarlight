package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;


// To MetaDataTokenDetails
public record MetaGranularScopes(
    @JsonProperty("scope")
    String scope,

    @JsonProperty("target_id")
    String[] targetId
) {}
