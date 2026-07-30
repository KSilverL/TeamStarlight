package com.example.tsldemo.DTOs.Request.LinkedIn;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

// To ContentMedia
@Getter
@Setter
public class ContentMediaDetails {
    @JsonProperty("id")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String id;

    public ContentMediaDetails(String id) {
        this.id = id;
    }
}
