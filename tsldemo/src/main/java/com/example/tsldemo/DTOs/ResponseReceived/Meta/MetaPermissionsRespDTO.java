package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Graph /me/permissions — what the user actually granted at the consent dialog, which can be a
 * subset of what was requested (each entry is "granted" or "declined"). Used to explain why a
 * Page lookup came back empty instead of leaving the UI with a silent empty list. */
public record MetaPermissionsRespDTO(

    @JsonProperty("data")
    MetaPermission[] data

) {
    public record MetaPermission(

        @JsonProperty("permission")
        String permission,

        @JsonProperty("status")
        String status

    ) {}
}
