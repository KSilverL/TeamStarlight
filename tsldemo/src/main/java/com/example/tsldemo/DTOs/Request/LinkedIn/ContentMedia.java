package com.example.tsldemo.DTOs.Request.LinkedIn;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

// To LinkedInPostReqDTO
@Getter
@Setter
public class ContentMedia {
    @JsonProperty("media")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private ContentMediaDetails media;

    public ContentMedia(ContentMediaDetails media) {
        this.media = media;
    }
}
