package com.example.tsldemo.CrossPlatformAPI;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/instagram")
public class InstagramAPIController {

    private final InstagramAPIService instagramAPIService;

    public InstagramAPIController(InstagramAPIService instagramAPIService) {
        this.instagramAPIService = instagramAPIService;
    }

    @PostMapping(value = "/post-video", consumes = "multipart/form-data")
    public ResponseEntity<String> postVideo(
            @RequestParam("video") MultipartFile video,
            @RequestParam("caption") String caption) throws Exception {

        String mediaId = instagramAPIService.postVideo(video, caption);
        return ResponseEntity.ok(mediaId);
    }
}