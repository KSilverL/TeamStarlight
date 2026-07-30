package com.example.tsldemo.CrossPlatformAPI;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.DTOs.Request.CrossPlatPostReqDTO;
import com.example.tsldemo.DTOs.Request.GlobalCrossPlatform.GlobalCredsReqDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.GlobalCredListRespDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.MetaPageInfo;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.DTOs.Request.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInVideoPostReqDTO;
import com.example.tsldemo.auth.JwtUtil;

import jakarta.servlet.http.HttpServletResponse;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@RestController
public class CrossPlatformController {

    private final CrossPlatformService crossPlatformService;
    private final JwtUtil jwtUtil;

    public CrossPlatformController(CrossPlatformService crossPlatformService, JwtUtil jwtUtil) {
        this.crossPlatformService = crossPlatformService;
        this.jwtUtil = jwtUtil;
    }

    //////////////////////////////////////////////////////// GLOBAL METHODS ////////////////////////////////////////////////////////
    @GetMapping("/global/getCompCreds")
    public ResponseEntity<?> getGlobalCompCreds(@RequestParam(value = "businessId", required = false) Long businessId,
                                            @RequestParam(value = "platforms", required = false) List<PlatformEnum> platforms) {
        
        List<GlobalCredListRespDTO> records = crossPlatformService.getGlobalCredentials(businessId, platforms);
        return ResponseEntity.ok(records);
    }

    @PostMapping("/global/addCompCreds")
    public ResponseEntity<?> addGlobalCompCreds(@RequestBody GlobalCredsReqDTO[] requestDTO) {
        
        crossPlatformService.saveGlobalCredentials(requestDTO);
        return ResponseEntity.ok("Credentials Added Successfully.");
    }

    @PutMapping("/global/updateCompCreds")
    public ResponseEntity<?> updateGlobalCompCreds(@RequestBody GlobalCredsReqDTO[] requestDTO) {
        
        crossPlatformService.updateGlobalCredentials(requestDTO);
        return ResponseEntity.ok("Credentials Updated Successfully.");
    }

    @DeleteMapping("/global/deleteCompCreds")
    public ResponseEntity<?> deleteGlobalCompCreds(@RequestParam(value = "businessId", required = false) Long businessId,
                                            @RequestParam(value = "platforms", required = false) List<PlatformEnum> platforms) {
        
        crossPlatformService.deleteGlobalCredentials(businessId, platforms);
        return ResponseEntity.ok("Credentials Deleted Successfully.");
    }

    /** All endpoints are scoped to the calling business, taken from the JWT — never from
     * anything the client claims in the request body — so one business can't read or act on
     * another's LinkedIn connection. */
    private int requireBusinessId(String authHeader) {
        int businessId = jwtUtil.extractBusinessId(authHeader);
        if (businessId == -1) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Missing or invalid authorization token");
        }
        return businessId;
    }

    //////////////////////////////////////////////////////// LINKEDIN METHODS ////////////////////////////////////////////////////////
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

    /** Posts a user-attached image. Sent as multipart/form-data (the raw image bytes plus a
     * text commentary), unlike the JSON text/video endpoints — the browser uploads a real file
     * here rather than referencing an already-rendered asset by id. */
    @PostMapping("/linkedin/post-image")
    public ResponseEntity<?> linkedInPostImage(
            @RequestParam("message") String message,
            @RequestParam("image") MultipartFile image,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        String postId = crossPlatformService.postImageToLinkedIn(businessId, message, image);
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

    //////////////////////////////////////////////////////// META METHODS ////////////////////////////////////////////////////////

    @PutMapping("/meta/addPageInfo")
    public ResponseEntity<?> addMetaCompPageInfo(@RequestBody Long businessId) {
        
        try {
            CrossPlatformOAuth crossPlatformOAuth = crossPlatformService.saveMetaPagesInfo(businessId);
            MetaPageInfo response = new MetaPageInfo();
            response.setPageIds(crossPlatformOAuth.getPageIdArray());
            response.setPageNames(crossPlatformOAuth.getPageNameArray());
            response.setIgUserIds(crossPlatformOAuth.getIgUserIdArray());
            response.setInstagramNotice(crossPlatformService.instagramNoticeFor(businessId));
            return ResponseEntity.ok(response);
        } catch (ResponseStatusException e) {
            // Spring Boot 4 drops the exception's reason from the default error body, so letting
            // this propagate would reach the browser as a bare "Bad Request". The reason IS the
            // payload here — it names the Meta permission or consent step the user has to fix —
            // so return it in a body the frontend can relay verbatim.
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("error", e.getReason() == null ? "Could not load Facebook Pages." : e.getReason()));
        }
    }

    @PostMapping("/linkedin/addCompCreds")
    public ResponseEntity<?> linkedCompCreds(
            @RequestBody LinkedInCredsReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        int businessId = requireBusinessId(authHeader);
        crossPlatformService.saveLinkedInCredentials(businessId, requestDTO);
        return ResponseEntity.ok("LinkedIn company credentials added successfully.");
    }
    
    @PostMapping("/linkedin/schedule-post")
    public ResponseEntity<?> linkedInSchedulePost(
            @RequestBody LinkedInPostReqDTO requestDTO,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

    	int businessId = requireBusinessId(authHeader);

        LinkedInPostReqDTO secureDto = new LinkedInPostReqDTO(
                requestDTO.message(),
                requestDTO.scheduledTime()
        );

        crossPlatformService.schedulePostToLinkedIn(businessId, secureDto);
        return ResponseEntity.ok(Map.of("status", "scheduled"));
        
    }

    @PostMapping("/meta/auth")
    public void metaAuth(HttpServletResponse response,
                         @RequestBody Long businessId,
                         @RequestParam(value = "force", defaultValue = "false") boolean force) throws IOException{
        crossPlatformService.authCodeMeta(businessId, response, force);
    }

    @GetMapping("/meta/callback")
    public void metaCallback(HttpServletResponse response,
                             @RequestParam(value = "code", required = true) String authCode,
                             @RequestParam(value = "state", required = true) String state) throws IOException {
        try {
            crossPlatformService.accessTokenMeta(authCode, state);
            crossPlatformService.redirectToFrontend(response, "meta", true);
        } catch (Exception e) {
            crossPlatformService.redirectToFrontend(response, "meta", false);
        }
    }

    @PostMapping("/meta/post")
    public ResponseEntity<?> metaPost(@ModelAttribute CrossPlatPostReqDTO requestDTO) throws IOException {
        try {
            List<String> postIdList = crossPlatformService.postToMeta(requestDTO);
            return ResponseEntity.ok(Map.of("Meta Post ok: ", postIdList));
        } catch (ResourceAccessException e) {
            // The upload never got an answer — a read timeout on a slow video, or Graph dropping
            // the connection. An unhandled throw would surface as a bare 500, which tells the
            // user nothing about whether to retry or shrink the video.
            return ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT)
                    .body(Map.of("error", "Facebook did not respond while the video was uploading. "
                            + "Large videos can exceed the upload window — try a shorter clip, or retry."));
        } catch (RestClientResponseException e) {
            // Graph rejected the post outright (bad page token, unsupported media, policy). Its
            // JSON body names the actual reason, so pass it through rather than swallowing it.
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("error", "Facebook rejected the post: " + e.getResponseBodyAsString()));
        }
    }
}
