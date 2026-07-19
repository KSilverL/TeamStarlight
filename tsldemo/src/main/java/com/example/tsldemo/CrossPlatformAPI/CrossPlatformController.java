package com.example.tsldemo.CrossPlatformAPI;

import com.example.tsldemo.DTOs.Request.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInVideoPostReqDTO;
import com.example.tsldemo.auth.JwtUtil;

import jakarta.servlet.http.HttpServletResponse;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.util.Map;

@RestController
public class CrossPlatformController {

    private final CrossPlatformService crossPlatformService;
    private final JwtUtil jwtUtil;

    public CrossPlatformController(CrossPlatformService crossPlatformService, JwtUtil jwtUtil) {
        this.crossPlatformService = crossPlatformService;
        this.jwtUtil = jwtUtil;
    }

    /** All four endpoints are scoped to the calling business, taken from the JWT — never from
     * anything the client claims in the request body — so one business can't read or act on
     * another's LinkedIn connection. */
    private int requireBusinessId(String authHeader) {
        int businessId = jwtUtil.extractBusinessId(authHeader);
        if (businessId == -1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Missing or invalid authorization token");
        }
        return businessId;
    }

    @PostMapping("/linkedin/auth")
    public void linkedInAuth(
            HttpServletResponse response,
            @RequestHeader(value = "Authorization", required = false) String authHeader) throws IOException {

        int businessId = requireBusinessId(authHeader);
        crossPlatformService.authCodeLinkedIn(businessId, response);
    }

    @GetMapping("/linkedin/callback")
    public void linkedInCallback(
            HttpServletResponse response,
            @RequestParam(value = "code", required = false) String authCode,
            @RequestParam(value = "state", required = false) String state) throws IOException {

        try {
            crossPlatformService.accessTokenLinkedIn(authCode, state);
            crossPlatformService.redirectToFrontend(response, true);
        } catch (Exception e) {
            crossPlatformService.redirectToFrontend(response, false);
        }
    }

    @PostMapping("/linkedin/post")
    public ResponseEntity<?> linkedInPost(
            @RequestBody LinkedInPostReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        String postId = crossPlatformService.postToLinkedIn(businessId, requestDTO);
        return ResponseEntity.ok(Map.of("PostId", postId));
    }

    @PostMapping("/linkedin/post-video")
    public ResponseEntity<?> linkedInPostVideo(
            @RequestBody LinkedInVideoPostReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        String postId = crossPlatformService.postVideoToLinkedIn(businessId, requestDTO);
        return ResponseEntity.ok(Map.of("PostId", postId));
    }

    @PostMapping("/linkedin/addCompCreds")
    public ResponseEntity<?> linkedCompCreds(
            @RequestBody LinkedInCredsReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        crossPlatformService.saveLinkedInCredentials(businessId, requestDTO);
        return ResponseEntity.ok("LinkedIn company credentials added successfully.");
    }
}
