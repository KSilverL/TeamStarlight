package com.example.tsldemo.DTOs.Request;

import org.springframework.web.multipart.MultipartFile;

import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class CrossPlatPostReqDTO{

    @JsonProperty("businessId")
    Long businessId;

    @JsonProperty("message")
    String message;

    @JsonProperty("media")
    MultipartFile media;

    // Meta Specific Stuff
    @JsonProperty("pageId")
    Long[] pageId;

    // For video
    @JsonProperty("title")
    String title;

    @JsonProperty("description")
    String description;

}