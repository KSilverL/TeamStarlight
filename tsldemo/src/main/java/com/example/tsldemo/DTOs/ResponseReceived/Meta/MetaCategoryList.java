package com.example.tsldemo.DTOs.ResponseReceived.Meta;

import com.fasterxml.jackson.annotation.JsonProperty;

public record MetaCategoryList(

    @JsonProperty("id")
    Long categoryId,

    @JsonProperty("name")
    String name

) {}
