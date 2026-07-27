package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

// To MetaUserInfoDTO
public record MetaDataUserInfo(

    @JsonProperty("access_token")
    String pageAccessToken,

    @JsonProperty("category")
    String category,

    @JsonProperty("category_list")
    MetaCategoryList[] categoryList,

    @JsonProperty("name")
    String pageName,

    @JsonProperty("id")
    Long pageId,

    @JsonProperty("tasks")
    String[] tasks

) {}
