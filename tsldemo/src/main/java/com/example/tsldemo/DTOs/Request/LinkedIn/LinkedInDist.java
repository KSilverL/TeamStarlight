package com.example.tsldemo.DTOs.Request.LinkedIn;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
// To LinkedInPostReqDTO
public class LinkedInDist {

    @JsonProperty("feedDistribution")
    private String feedDistribution;

    @JsonProperty("targetEntities")
    private List<String> targetEntities;

    @JsonProperty("thirdPartyDistributionChannels")
    private List<String> thirdPartyDistributionChannels;

    public LinkedInDist(String feedDistribution, List<String> targetEntities, List<String> thirdPartyDistributionChannels) {
        this.feedDistribution = feedDistribution;
        this.targetEntities = targetEntities;
        this.thirdPartyDistributionChannels = thirdPartyDistributionChannels;
    }

}