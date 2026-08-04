package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * A post's publish state, read back after its scheduled time has passed.
 *
 * <p>When Facebook holds the schedule we never see the publish happen, so the alternative to
 * asking is assuming — and a post Graph quietly dropped (Page unpublished, token revoked in the
 * meantime) would show in the calendar as a success that never happened.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record MetaPublishStateRespDTO(

    @JsonProperty("id")
    String id,

    @JsonProperty("is_published")
    Boolean isPublished
) {}
