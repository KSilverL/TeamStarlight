package com.example.tsldemo.DTOs.Request;

import org.springframework.web.multipart.MultipartFile;

import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class CrossPlatPostReqDTO{

    @JsonProperty("businessId")
    int businessId;

    @JsonProperty("message")
    String message;

    @JsonProperty("media")
    MultipartFile media;

}