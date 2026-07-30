package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Graph /me — which Facebook user the stored token belongs to. Reported back when a Page lookup
 * finds nothing, because "connected as the wrong account" and "connected but no Page picked" are
 * otherwise indistinguishable to the user. */
public record MetaIdentityRespDTO(

    @JsonProperty("id")
    String id,

    @JsonProperty("name")
    String name

) {}
