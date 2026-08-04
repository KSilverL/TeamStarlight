package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

// To MetaTokenDetails
public record MetaDataTokenDetails(
    
    @JsonProperty("app_id")
    String appId,

    @JsonProperty("type")
    String type,

    @JsonProperty("application")
    String application,

    @JsonProperty("data_access_expires_at")
    Long dataAccessExpiresAt,

    @JsonProperty("expires_at")
    Long expiresAt,

    @JsonProperty("is_valid")
    Boolean isValid,

    @JsonProperty("issued_at")
    Long issuedAt,

    @JsonProperty("scopes")
    String[] scope,

    @JsonProperty("granular_scopes")
    MetaGranularScopes[] granularScopes,

    @JsonProperty("user_id")
    String userId
) {}
