package com.example.tsldemo.CrossPlatformAPI;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.DTOs.Request.CrossPlatPostReqDTO;
import com.example.tsldemo.DTOs.Request.GlobalCrossPlatform.GlobalCredsReqDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.GlobalCredListRespDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.MetaPageInfo;
import com.example.tsldemo.ENUMS.PlatformEnum;

import jakarta.servlet.http.HttpServletResponse;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@RestController
public class CrossPlatformController {

    private final CrossPlatformService crossPlatformService;

    public CrossPlatformController(CrossPlatformService crossPlatformService) {
        this.crossPlatformService = crossPlatformService;
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

    //////////////////////////////////////////////////////// LINKEDIN METHODS ////////////////////////////////////////////////////////
    @PostMapping("/linkedin/auth")
    public void linkedInAuth(HttpServletResponse response, @RequestBody Long businessId) throws IOException{

        crossPlatformService.authCodeLinkedIn(businessId, response);

    }

    @GetMapping("/linkedin/callback")
    public ResponseEntity<?> linkedInCallback(@RequestParam(value = "code", required = true) String authCode,
                                        @RequestParam(value = "state", required = true) String state) {

        crossPlatformService.accessTokenLinkedIn(authCode, state);
        
        return ResponseEntity.ok("Access token retrieved and saved successfully.");
    }

    @PostMapping("/linkedin/post")
    public ResponseEntity<?> linkedInPost(@ModelAttribute CrossPlatPostReqDTO requestDTO) {

        String postId = crossPlatformService.postToLinkedIn(requestDTO);
        return ResponseEntity.ok(Map.of("PostId", postId));
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

    //////////////////////////////////////////////////////// META METHODS ////////////////////////////////////////////////////////

    @PutMapping("/meta/addPageInfo")
    public ResponseEntity<?> addMetaCompPageInfo(@RequestBody Long businessId) {
        
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformService.saveMetaPagesInfo(businessId);
        MetaPageInfo response = new MetaPageInfo();
        response.setPageIds(crossPlatformOAuth.getPageIdArray());
        response.setPageNames(crossPlatformOAuth.getPageNameArray());
        return ResponseEntity.ok(response);
    }
    
    @PostMapping("/meta/auth")
    public void metaAuth(HttpServletResponse response, @RequestBody Long businessId) throws IOException{

        crossPlatformService.authCodeMeta(businessId, response);

    }

    @GetMapping("/meta/callback")
    public ResponseEntity<?> metaCallback(@RequestParam(value = "code", required = true) String authCode,
                                        @RequestParam(value = "state", required = true) String state) {

        crossPlatformService.accessTokenMeta(authCode, state);
        
        return ResponseEntity.ok("Access token retrieved and saved successfully.");
    }

    @PostMapping("/meta/post")
    public ResponseEntity<?> metaPost(@ModelAttribute CrossPlatPostReqDTO requestDTO) throws IOException {

        List<String> postIdList = crossPlatformService.postToMeta(requestDTO);
        return ResponseEntity.ok(Map.of("Meta Post ok: ", postIdList));
    }
    
}
