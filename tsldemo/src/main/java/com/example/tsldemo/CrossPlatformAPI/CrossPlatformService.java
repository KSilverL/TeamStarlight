package com.example.tsldemo.CrossPlatformAPI;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;

import org.apache.tika.Tika;
import org.springframework.beans.factory.annotation.*;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.DTOs.Request.CrossPlatPostReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedIn.ContentMediaDetails;
import com.example.tsldemo.DTOs.Request.LinkedIn.ContentMedia;
import com.example.tsldemo.DTOs.Request.LinkedIn.ContentMediaDetails;
import com.example.tsldemo.DTOs.Request.LinkedIn.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedIn.LinkedInIniUpReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedIn.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInAuthRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInIniMediaUpRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInUserInfoDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;

import jakarta.servlet.http.HttpServletResponse;

@Service
public class CrossPlatformService {

    @Autowired
    private CrossPlatformRepository crossPlatformRepository;

	private final RestClient restClient;

    public CrossPlatformService(RestClient restClient) {
        this.restClient = restClient;
    }
	
    //////////////////////////////////////////////////////// LINKEDIN METHODS ////////////////////////////////////////////////////////
    public void authCodeLinkedIn(LinkedInCredsReqDTO requestDTO, HttpServletResponse response) throws IOException {
        String state = UUID.randomUUID().toString();

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(requestDTO.businessId(), PlatformEnum.LINKEDIN);

        if (crossPlatformOAuth.getAccessToken() == null || crossPlatformOAuth.getExpiresAt() == null || !crossPlatformOAuth.getExpiresAt().isAfter(Instant.now())) {

            String authorizationUrl =
                "https://www.linkedin.com/oauth/v2/authorization"
                + "?response_type=code"
                + "&client_id=" + URLEncoder.encode(crossPlatformOAuth.getClientId(), StandardCharsets.UTF_8)
                + "&redirect_uri=" + URLEncoder.encode("http://localhost:8081/linkedin/callback", StandardCharsets.UTF_8)
                + "&state=" + URLEncoder.encode(state, StandardCharsets.UTF_8)
                + "&scope=" + URLEncoder.encode("openid profile email w_member_social", StandardCharsets.UTF_8);

            response.sendRedirect(authorizationUrl);    

            crossPlatformOAuth.setState(state);
            crossPlatformRepository.save(crossPlatformOAuth);
        }
    }

    public LinkedInAuthRespDTO accessTokenLinkedIn(String authorizationCode, String state) {
        RestClient restClient = RestClient.create();

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByStateAndPlatform(state, PlatformEnum.LINKEDIN);

        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("grant_type", "authorization_code");
        form.add("code", authorizationCode);
        form.add("redirect_uri", "http://localhost:8081/linkedin/callback");
        form.add("client_id", crossPlatformOAuth.getClientId());
        form.add("client_secret", crossPlatformOAuth.getClientSecret());

        LinkedInAuthRespDTO token = restClient.post()
                .uri("https://www.linkedin.com/oauth/v2/accessToken")
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(form)
                .retrieve()
                .body(LinkedInAuthRespDTO.class);

        crossPlatformOAuth.setAccessToken(token.accessToken());
        crossPlatformOAuth.setExpiresAt(Instant.now().plusSeconds(token.expiresIn()));

        crossPlatformRepository.save(crossPlatformOAuth);

        return token;
    }

    public String postToLinkedIn(CrossPlatPostReqDTO requestDTO) {

        // Message reediting [Temp stop making given not our problem]
        // if (requestDTO.getMessage().contains("(") || requestDTO.getMessage().contains(")")) {
        //     // Case if have {} []
        //     if (requestDTO.getMessage().contains("{") || requestDTO.getMessage().contains("}") || requestDTO.getMessage().contains("[") || requestDTO.getMessage().contains("]")) {
        //         String result = requestDTO.getMessage().replaceAll("[^()\\[\\]{}]", "");
        //         if (result.substring(0, 1) == "(" || result.substring(0, 1) == ")") {
        //             requestDTO.setMessage(requestDTO.getMessage().replace("(", "\\("));
        //             requestDTO.setMessage(requestDTO.getMessage().replace(")", "\\)"));
        //         }
        //     }
        //     // Case if no {} []
        //     else {
        //         requestDTO.setMessage(requestDTO.getMessage().replace("(", "\\("));
        //         requestDTO.setMessage(requestDTO.getMessage().replace(")", "\\)"));
        //     }
        // }

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(requestDTO.getBusinessId(), PlatformEnum.LINKEDIN);

        if (crossPlatformOAuth.getUrn() == null) {
            LinkedInUserInfoDTO linkedInUserInfo = restClient.get()
                .uri("https://api.linkedin.com/v2/userinfo")
                .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
                .retrieve()
                .body(LinkedInUserInfoDTO.class);

            crossPlatformOAuth.setUrn("urn:li:person:" + linkedInUserInfo.sub());
            crossPlatformRepository.save(crossPlatformOAuth);
        }

        LinkedInIniMediaUpRespDTO mediaUploadResponse = new LinkedInIniMediaUpRespDTO(null);

        LinkedInPostReqDTO requestBody = new LinkedInPostReqDTO(
            crossPlatformOAuth.getUrn(),
            requestDTO.getMessage()
        );

        if (requestDTO.getMedia() != null && !requestDTO.getMedia().isEmpty()) {
            mediaUploadResponse = uploadMedia(requestDTO, crossPlatformOAuth);
            requestBody.setContent(new ContentMedia(new ContentMediaDetails(mediaUploadResponse.value().mediaUrn())));
        }

        ResponseEntity<Void> response = restClient.post()
                .uri("https://api.linkedin.com/rest/posts")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
                .header("LinkedIn-Version", "202606")
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(requestBody)
                .retrieve()
                .toBodilessEntity();
        
        return response.getHeaders().getFirst("x-restli-id");
    }

    public void saveLinkedInCredentials(LinkedInCredsReqDTO creds) {

        CrossPlatformOAuth crossPlatformOAuth = new CrossPlatformOAuth();
        crossPlatformOAuth.setBusinessId(creds.businessId());
        crossPlatformOAuth.setClientId(creds.clientId());
        crossPlatformOAuth.setClientSecret(creds.clientSecret());
        crossPlatformOAuth.setPlatform(PlatformEnum.LINKEDIN);

        crossPlatformRepository.save(crossPlatformOAuth);
    }

    public LinkedInIniMediaUpRespDTO uploadMedia(CrossPlatPostReqDTO requestDTO, CrossPlatformOAuth crossPlatformOAuth) {

        Tika tika = new Tika();
        String mime = "";
        LinkedInIniMediaUpRespDTO iniResponse = null;
        String url = "";
        LinkedInIniUpReqDTO requestBody = new LinkedInIniUpReqDTO(crossPlatformOAuth.getUrn(), null, null, null);
        try {
            mime = tika.detect(requestDTO.getMedia().getInputStream());

            if (mime.startsWith("image/")) {
                url = "https://api.linkedin.com/rest/images?action=initializeUpload";
            }
            else if (mime.startsWith("video/")) {
                url = "https://api.linkedin.com/rest/videos?action=initializeUpload";
                requestBody.getInitializeUploadRequest().setFileSize(requestDTO.getMedia().getSize());
                requestBody.getInitializeUploadRequest().setUploadCaptions(false);
                requestBody.getInitializeUploadRequest().setUploadThumbnail(false);
            }


            // Initialize Upload
            iniResponse = restClient.post()
                .uri(url)
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
                .header("LinkedIn-Version", "202606")
                .body(requestBody)
                .retrieve()
                .body(LinkedInIniMediaUpRespDTO.class);
            
            // Upload Media
            if (mime.startsWith("image/")) {
                restClient.put()
                    .uri(iniResponse.value().uploadUrl())
                    .contentType(MediaType.parseMediaType(requestDTO.getMedia().getContentType()))
                    .body(requestDTO.getMedia().getBytes())
                    .retrieve()
                    .toBodilessEntity();
            }
            else {
                restClient.put()
                    .uri(iniResponse.value().uploadInstructions().uploadUrl())
                    .contentType(MediaType.parseMediaType(requestDTO.getMedia().getContentType()))
                    .body(requestDTO.getMedia().getBytes())
                    .retrieve()
                    .toBodilessEntity();
            }
        } catch (IOException e) {
            e.printStackTrace();
        }

        return iniResponse;
    }

}
