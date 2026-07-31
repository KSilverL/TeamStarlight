package com.example.tsldemo.DTOs.Request;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Creates a scheduled post.
 *
 * <p>{@code scheduledTime} accepts either a bare wall-clock time ("2026-07-18T10:00:00"), in
 * which case {@code timezone} — or the server's configured default — decides what instant that
 * means, or a fully-qualified one ("2026-07-18T10:00:00+01:00", "…Z") which carries its own
 * offset and is taken at face value. Sending the offset is preferred: it removes the guess.
 */
public record ScheduledPostReqDTO(

    /** "linkedin", or "facebook"/"meta". */
    @JsonProperty("platform")
    String platform,

    @JsonProperty("scheduled_time")
    String scheduledTime,

    /** IANA zone name, e.g. "Europe/Dublin". Ignored when scheduledTime carries an offset. */
    @JsonProperty("timezone")
    String timezone,

    @JsonProperty("message")
    String message,

    @JsonProperty("hashtags")
    List<String> hashtags,

    /** Required for Facebook: the Page(s) to publish to. */
    @JsonProperty("page_ids")
    List<Long> pageIds
) {}
