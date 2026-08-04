package com.example.tsldemo.DTOs.Request.LinkedIn;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class LinkedInPostReqDTO {

    @JsonProperty("author")
    private String author;

    @JsonProperty("commentary")
    private String commentary;

    @JsonProperty("visibility")
    private String visibility;

    @JsonProperty("distribution")
    private LinkedInDist distribution;

    @JsonProperty("lifecycleState")
    private String lifecycleState;

    @JsonProperty("content")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private ContentMedia content;

    @JsonProperty("isReshareDisabledByAuthor")
    private Boolean isReshareDisabledByAuthor;

    public LinkedInPostReqDTO(String author, String commentary) {
        this.author = author;
        this.commentary = commentary;
        this.visibility = "PUBLIC";
        this.distribution = new LinkedInDist("MAIN_FEED", List.of(), List.of());
        this.lifecycleState = "PUBLISHED";
        this.content = null;
        this.isReshareDisabledByAuthor = false;

    }
}