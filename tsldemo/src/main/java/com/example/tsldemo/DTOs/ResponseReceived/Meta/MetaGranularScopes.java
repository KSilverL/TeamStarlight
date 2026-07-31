package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;


// To MetaDataTokenDetails
public record MetaGranularScopes(
    @JsonProperty("scope")
    String scope,

    // Graph names this "target_ids" (plural). Mapped as "target_id" it never bound, so every
    // grant looked Page-less. Absent entirely means the grant covers all current and future
    // Pages — Facebook only lists ids when the user picked specific Pages.
    @JsonProperty("target_ids")
    String[] targetIds
) {}
