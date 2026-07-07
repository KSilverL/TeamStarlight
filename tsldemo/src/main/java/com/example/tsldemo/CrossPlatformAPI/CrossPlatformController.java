package com.example.tsldemo.CrossPlatformAPI;

import com.example.tsldemo.DTOs.Request.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;

import jakarta.servlet.http.HttpServletResponse;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.util.Map;

@RestController
public class CrossPlatformController {

    private final CrossPlatformService crossPlatformService;

    public CrossPlatformController(CrossPlatformService crossPlatformService) {
        this.crossPlatformService = crossPlatformService;
    }

    @PostMapping("/linkedin/auth")
    public void linkedInAuth(HttpServletResponse response, @RequestBody LinkedInPostReqDTO requestDTO) throws IOException{

        crossPlatformService.authCodeLinkedIn(requestDTO, response);

    }

    @GetMapping("/linkedin/callback")
    public ResponseEntity<?> linkedInCallback(@RequestParam(value = "code", required = false) String authCode,
                                        @RequestParam(value = "state", required = false) String state) {

        crossPlatformService.accessTokenLinkedIn(authCode, state);
        
        return ResponseEntity.ok("Access token retrieved and saved successfully.");
    }

    @PostMapping("/linkedin/post")
    public ResponseEntity<?> linkedInPost(@RequestBody LinkedInPostReqDTO requestDTO) {

        String postId = crossPlatformService.postToLinkedIn(requestDTO);
        return ResponseEntity.ok(Map.of("PostId", postId));
    }

    @PostMapping("/linkedin/addCompCreds")
    public ResponseEntity<?> linkedCompCreds(@RequestBody LinkedInCredsReqDTO requestDTO) {
        
        crossPlatformService.saveLinkedInCredentials(requestDTO);
        return ResponseEntity.ok("LinkedIn company credentials added successfully.");
    }
}
