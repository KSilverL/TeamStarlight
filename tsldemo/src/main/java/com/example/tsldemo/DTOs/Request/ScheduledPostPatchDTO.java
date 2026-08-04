package com.example.tsldemo.DTOs.Request;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Partial update of a scheduled post — every field is optional and a null one means "leave
 * this alone". Only posts still in SCHEDULED can be patched.
 *
 * <p>Note this cannot distinguish "omitted" from "explicitly null", which is fine here: there
 * is no field a caller would want to clear (an empty hashtag list is sent as {@code []}).
 */
public record ScheduledPostPatchDTO(

    @JsonProperty("scheduled_time")
    String scheduledTime,

    @JsonProperty("timezone")
    String timezone,

    @JsonProperty("message")
    String message,

    @JsonProperty("hashtags")
    List<String> hashtags,

    @JsonProperty("page_ids")
    List<Long> pageIds
) {}
