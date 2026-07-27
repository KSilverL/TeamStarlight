package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

// To MetaUserInfoDTO
public record MetaPaging(

    @JsonProperty("cursors")
    MetaCursors cursors

) {}
