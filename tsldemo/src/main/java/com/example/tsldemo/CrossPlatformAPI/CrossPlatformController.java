package com.example.tsldemo.CrossPlatformAPI;

import com.example.tsldemo.DTOs.Request.CrossPlatPostReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedIn.LinkedInCredsReqDTO;

import jakarta.servlet.http.HttpServletResponse;

import org.apache.tika.Tika;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Map;

@RestController
public class CrossPlatformController {

    private final CrossPlatformService crossPlatformService;

    public CrossPlatformController(CrossPlatformService crossPlatformService) {
        this.crossPlatformService = crossPlatformService;
    }

    //////////////////////////////////////////////////////// LINKEDIN METHODS ////////////////////////////////////////////////////////
    @PostMapping("/linkedin/auth")
    public void linkedInAuth(HttpServletResponse response, @RequestBody LinkedInCredsReqDTO requestDTO) throws IOException{

        crossPlatformService.authCodeLinkedIn(requestDTO, response);

    }

    @GetMapping("/linkedin/callback")
    public ResponseEntity<?> linkedInCallback(@RequestParam(value = "code", required = false) String authCode,
                                        @RequestParam(value = "state", required = false) String state) {

        crossPlatformService.accessTokenLinkedIn(authCode, state);
        
        return ResponseEntity.ok("Access token retrieved and saved successfully.");
    }

    @PostMapping("/linkedin/post")
    public ResponseEntity<?> linkedInPost(@ModelAttribute CrossPlatPostReqDTO requestDTO) {

        String postId = crossPlatformService.postToLinkedIn(requestDTO);
        return ResponseEntity.ok(Map.of("PostId", postId));
    }

    @PostMapping("/linkedin/addCompCreds")
    public ResponseEntity<?> linkedCompCreds(@RequestBody LinkedInCredsReqDTO requestDTO) {
        
        crossPlatformService.saveLinkedInCredentials(requestDTO);
        return ResponseEntity.ok("LinkedIn company credentials added successfully.");
    }

    // @PostMapping("/MultipartFileTest")
    // public ResponseEntity<?> testMultipartFile(@RequestBody MultipartFile media) {
        
    //     System.out.println("Detected Content Type: ");
    //     Tika tika = new Tika();

    //     String mime = null;
    //     try {
    //         mime = tika.detect(media.getInputStream());
    //     } catch (IOException e) {
    //         // TODO Auto-generated catch block
    //         e.printStackTrace();
    //     }

    //     System.out.println(mime);
        
    //     return ResponseEntity.ok("File uploaded successfully.");
    // }
}
