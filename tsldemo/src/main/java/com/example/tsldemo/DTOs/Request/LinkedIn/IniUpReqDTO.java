package com.example.tsldemo.DTOs.Request.LinkedIn;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import lombok.Getter;
import lombok.Setter;

// Used with LinkedIninitializeUploadReqDTO
@Getter
@Setter
public class IniUpReqDTO {
    @JsonProperty("owner")
    private String ownerUrn;

    @JsonProperty("fileSizeBytes")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private Long fileSize;

    @JsonProperty("uploadCaptions")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private Boolean uploadCaptions;

    @JsonProperty("uploadThumbnail")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private Boolean uploadThumbnail;

    public IniUpReqDTO(String ownerUrn, Long fileSize, Boolean uploadCaptions, Boolean uploadThumbnail) {
        this.ownerUrn = ownerUrn;
        this.fileSize = fileSize;
        this.uploadCaptions = uploadCaptions;
        this.uploadThumbnail = uploadThumbnail;
    }
}