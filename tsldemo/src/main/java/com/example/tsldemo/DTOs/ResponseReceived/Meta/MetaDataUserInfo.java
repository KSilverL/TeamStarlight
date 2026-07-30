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
    String[] tasks,

    /** Null unless the Page has an Instagram Business/Creator account linked to it — and only
     * populated at all when the request asks for it explicitly, since Graph omits this field
     * from the default field set on /me/accounts. */
    @JsonProperty("instagram_business_account")
    MetaInstagramAccount instagramBusinessAccount

) {}
