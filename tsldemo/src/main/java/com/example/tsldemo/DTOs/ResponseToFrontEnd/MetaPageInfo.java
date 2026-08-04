package com.example.tsldemo.DTOs.ResponseToFrontEnd;

import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class MetaPageInfo {
    
    @JsonProperty("pageIds")
    Long[] pageIds;

    @JsonProperty("pageNames")
    String[] pageNames;

}
