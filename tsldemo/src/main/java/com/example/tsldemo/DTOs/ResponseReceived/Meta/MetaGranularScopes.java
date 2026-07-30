package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;


// To MetaDataTokenDetails
public record MetaGranularScopes(
    @JsonProperty("scope")
    String scope,

    /** The specific assets (Page ids, Instagram account ids) this permission was granted over.
     * Graph names this "target_ids", plural — spelled "target_id" here previously, which meant it
     * silently parsed as null and the one field that says which Pages a token can actually see was
     * never readable. Absent for permissions that aren't asset-scoped (public_profile, email). */
    @JsonProperty("target_ids")
    String[] targetIds
) {}
