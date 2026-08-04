package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

public record MetaUserInfoDTO(
    @JsonProperty("data")
    MetaDataUserInfo[] data,

    @JsonProperty("paging")
    MetaPaging paging

) {}
