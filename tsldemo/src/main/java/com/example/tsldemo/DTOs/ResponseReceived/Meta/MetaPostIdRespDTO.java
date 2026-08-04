package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * What Graph returns after creating a post: {@code {"id": "<page_id>_<post_id>"}}.
 *
 * <p>The immediate-publish path reads the body as a raw String because nothing needs it back,
 * but a scheduled post has to be cancellable and re-timeable later, and this id is the only
 * handle Graph gives us for that — so it gets parsed and stored.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record MetaPostIdRespDTO(

    @JsonProperty("id")
    String id,

    /** Present on /photos and /videos responses; unused here but kept so the shapes match. */
    @JsonProperty("post_id")
    String postId
) {}
