package com.example.tsldemo.DTOs.Request;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Request to publish an already-rendered video as an Instagram Reel.
 *
 * Note there is no businessId here by design — it comes from the caller's JWT. The pageIds are
 * the Facebook Pages picked in the Brand Profile: an Instagram post is published through the Page
 * its account is linked to, so the Page is how the account and its token are reached. */
public record InstagramVideoPostReqDTO(

    @JsonProperty("jobId")
    String jobId,

    @JsonProperty("caption")
    String caption,

    @JsonProperty("pageIds")
    List<Long> pageIds

) {}
