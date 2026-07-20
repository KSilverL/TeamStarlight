package com.example.tsldemo.DTOs.ResponseReceived.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

public record LinkedInAuthRespDTO(

    @JsonProperty("access_token")
    String accessToken,

    @JsonProperty("expires_in")
    Long expiresIn,

    // The scopes LinkedIn actually granted. This can be narrower than what was requested:
    // scopes the app's products don't cover are dropped silently rather than rejected, so
    // this is the only way to tell a posting-capable token from a sign-in-only one.
    @JsonProperty("scope")
    String scope

){}