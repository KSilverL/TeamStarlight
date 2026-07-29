package com.example.tsldemo.DTOs.Request.LinkedIn;

import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class LinkedInIniUpReqDTO {
    @JsonProperty("initializeUploadRequest")
    private IniUpReqDTO initializeUploadRequest;

    public LinkedInIniUpReqDTO(String ownerUrn, Long fileSize, Boolean uploadCaptions, Boolean uploadThumbnail) {
        this.initializeUploadRequest = new IniUpReqDTO(ownerUrn, fileSize, uploadCaptions, uploadThumbnail);
    }
}
