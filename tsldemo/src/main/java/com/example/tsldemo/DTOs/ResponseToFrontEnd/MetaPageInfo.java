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

    /** Index-aligned with pageIds; null where that Page has no Instagram account linked. Lets the
     * Page picker mark which Pages an Instagram post can actually go through, instead of the user
     * discovering it only when publishing fails. */
    @JsonProperty("igUserIds")
    String[] igUserIds;

}
