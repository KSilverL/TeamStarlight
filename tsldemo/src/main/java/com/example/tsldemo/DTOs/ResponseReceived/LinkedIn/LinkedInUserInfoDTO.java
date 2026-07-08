package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInUserInfoDTO(
    @JsonProperty("sub")
    String sub,
    @JsonProperty("name")
    String name,
    @JsonProperty("locale")
    Locale locale,
    @JsonProperty("given_name")
    String givenName,
    @JsonProperty("family_name")
    String familyName,
    @JsonProperty("email")
    String email,
    @JsonProperty("picture")
    String picture
) {}
