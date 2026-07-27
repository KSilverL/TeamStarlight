package com.example.tsldemo.CrossPlatformAPI;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
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
import com.example.tsldemo.DTOs.Request.GlobalCrossPlatform.GlobalCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedIn.ContentMediaDetails;
import com.example.tsldemo.DTOs.Request.LinkedIn.ContentMedia;
import com.example.tsldemo.DTOs.Request.LinkedIn.LinkedInIniUpReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedIn.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInAuthRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInIniMediaUpRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInUserInfoDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaAuthAccessRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaDataUserInfo;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaTokenDetails;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaUserInfoDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.GlobalCredListRespDTO;
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
    //////////////////////////////////////////////////////// GLOBAL METHODS ////////////////////////////////////////////////////////
    public List<GlobalCredListRespDTO> getGlobalCredentials(Long businessId, List<PlatformEnum> platforms) {

        List<GlobalCredListRespDTO> globalCredList = new ArrayList<>();
        List<CrossPlatformOAuth> crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatformIn(businessId, platforms);
        for (CrossPlatformOAuth cred : crossPlatformOAuth) {
            GlobalCredListRespDTO globalCredentials = new GlobalCredListRespDTO();
            globalCredentials.setBusinessId(cred.getBusinessId());
            globalCredentials.setClientId(cred.getClientId());
            globalCredentials.setClientSecret(cred.getClientSecret());
            globalCredentials.setPageIdArray(cred.getPageIdArray());
            globalCredentials.setPageNameArray(cred.getPageNameArray());
            globalCredentials.setPlatform(cred.getPlatform());
            System.out.println("Created some records, adding to list");
            globalCredList.add(globalCredentials);
        }
        return globalCredList;
    }

    public void saveGlobalCredentials(GlobalCredsReqDTO[] creds) {

        for (GlobalCredsReqDTO cred : creds) {
            CrossPlatformOAuth crossPlatformOAuth = new CrossPlatformOAuth();
            crossPlatformOAuth.setBusinessId(cred.businessId());
            crossPlatformOAuth.setClientId(cred.clientId());
            crossPlatformOAuth.setClientSecret(cred.clientSecret());
            crossPlatformOAuth.setPlatform(cred.platform());

            crossPlatformRepository.save(crossPlatformOAuth);
        }
    }

    public void updateGlobalCredentials(GlobalCredsReqDTO[] creds) {

        for (GlobalCredsReqDTO cred : creds) {
            CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(cred.businessId(), cred.platform());
            crossPlatformOAuth.setClientId(cred.clientId());
            crossPlatformOAuth.setClientSecret(cred.clientSecret());

            crossPlatformRepository.save(crossPlatformOAuth);
        }
    }

    public void deleteGlobalCredentials(Long businessId, List<PlatformEnum> platforms) {
        crossPlatformRepository.deleteByBusinessIdAndPlatformIn(businessId, platforms);
    }
    
    //////////////////////////////////////////////////////// LINKEDIN METHODS ////////////////////////////////////////////////////////
    public void authCodeLinkedIn(Long businessId, HttpServletResponse response) throws IOException {
        String state = UUID.randomUUID().toString();

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.LINKEDIN);

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

    //////////////////////////////////////////////////////// META METHODS ////////////////////////////////////////////////////////
    public void authCodeMeta(Long businessId, HttpServletResponse response) throws IOException {

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.META);

        String state = UUID.randomUUID().toString();

        if (crossPlatformOAuth.getAccessToken() == null || crossPlatformOAuth.getExpiresAt() == null || !crossPlatformOAuth.getExpiresAt().isAfter(Instant.now())) {

            String authorizationUrl =
                "https://www.facebook.com/v25.0/dialog/oauth"
                + "?response_type=code"
                + "&client_id=" + URLEncoder.encode(crossPlatformOAuth.getClientId(), StandardCharsets.UTF_8)
                + "&redirect_uri=" + URLEncoder.encode("http://localhost:8081/meta/callback", StandardCharsets.UTF_8)
                + "&state=" + URLEncoder.encode(state, StandardCharsets.UTF_8)
                + "&scope=" + URLEncoder.encode("pages_show_list,pages_manage_posts,pages_read_engagement", StandardCharsets.UTF_8);

            response.sendRedirect(authorizationUrl);    

            crossPlatformOAuth.setState(state);
            crossPlatformRepository.save(crossPlatformOAuth);
        }
    }

    public MetaAuthAccessRespDTO accessTokenMeta(String metaAuthCode, String state) {
        RestClient restClient = RestClient.create();

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByStateAndPlatform(state, PlatformEnum.META);

        MetaAuthAccessRespDTO token = restClient.get()
                .uri(uriBuilder -> uriBuilder
                    .scheme("https")
                    .host("graph.facebook.com")
                    .path("/v25.0/oauth/access_token")
                    .queryParam("client_id", crossPlatformOAuth.getClientId())
                    .queryParam("redirect_uri", "http://localhost:8081/meta/callback")
                    .queryParam("client_secret", crossPlatformOAuth.getClientSecret())
                    .queryParam("code", metaAuthCode)
                    .build())
                .retrieve()
                .body(MetaAuthAccessRespDTO.class);

        crossPlatformOAuth.setAccessToken(token.accessToken());
        if (token.expiresIn() == null || token.expiresIn() == 0){
            MetaTokenDetails tokenDetails = restClient.get()
                .uri(uriBuilder -> uriBuilder
                    .scheme("https")
                    .host("graph.facebook.com")
                    .path("/debug_token")
                    .queryParam("input_token", token.accessToken())
                    .queryParam("access_token", crossPlatformOAuth.getClientId() + "|" + crossPlatformOAuth.getClientSecret())
                    .build())
                .retrieve()
                .body(MetaTokenDetails.class);
            if (tokenDetails.data().dataAccessExpiresAt() != null){
                crossPlatformOAuth.setExpiresAt(Instant.ofEpochSecond(tokenDetails.data().dataAccessExpiresAt()));
            }
        }
        else {
            crossPlatformOAuth.setExpiresAt(Instant.now().plusSeconds(token.expiresIn()));
        }
        crossPlatformRepository.save(crossPlatformOAuth);

        return token;
    }

    public CrossPlatformOAuth saveMetaPagesInfo(Long businessId) {
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.META);

        System.out.println("Start Post Method");
        System.out.println("PageId not found, retrieving data");
        MetaUserInfoDTO metaUserInfo = restClient.get()
            .uri("https://graph.facebook.com/v25.0/me/accounts")
            .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
            .retrieve()
            .body(MetaUserInfoDTO.class);

        crossPlatformOAuth.setPageIdArray(Arrays.stream(metaUserInfo.data()).map(MetaDataUserInfo::pageId).toArray(Long[]::new));
        crossPlatformOAuth.setPageNameArray(Arrays.stream(metaUserInfo.data()).map(MetaDataUserInfo::pageName).toArray(String[]::new));
        crossPlatformRepository.save(crossPlatformOAuth);

        return crossPlatformOAuth;
    }

    public List<String> postToMeta(CrossPlatPostReqDTO requestDTO) throws IOException {

        System.out.println("Starting Post Meta Method");
        System.out.println("businessId: " + requestDTO.getBusinessId());
        System.out.println("message: " + requestDTO.getMessage());
        System.out.println("media: " + requestDTO.getMedia());
        System.out.println("pageId: " + requestDTO.getPageId());
        List<CrossPlatformOAuth> crossPlatformOAuthList = crossPlatformRepository.findAll();
        System.out.println("businessIdFromDB: " + crossPlatformOAuthList.get(0).getBusinessId());
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(requestDTO.getBusinessId(), PlatformEnum.META);
        System.out.println("Meta Credentials Found!");

        MetaUserInfoDTO metaUserInfo = restClient.get()
            .uri("https://graph.facebook.com/v25.0/me/accounts")
            .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
            .retrieve()
            .body(MetaUserInfoDTO.class);
        
        List<String> postIds = new ArrayList<>();
        
        for (Long pageId : requestDTO.getPageId()) {
            // Body (Form) [No MetaPostReqDTO]
            System.out.println("Create post body");
            MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
            form.add("message", requestDTO.getMessage());
            form.add("access_token", Arrays.stream(metaUserInfo.data())
                        .filter(page -> page.pageId().equals(pageId))
                        .map(MetaDataUserInfo::pageAccessToken)
                        .toList().get(0));

            String url = "https://graph.facebook.com/v25.0/{page_id}/feed";

            if (requestDTO.getMedia() != null && !requestDTO.getMedia().isEmpty()) {
                String mime = "";
                Tika tika = new Tika();
                mime = tika.detect(requestDTO.getMedia().getInputStream());
                form.add("file", requestDTO.getMedia().getResource());

                if (mime.startsWith("image/")) {
                    url = "https://graph.facebook.com/v25.0/{page_id}/photos";
                }
                else if (mime.startsWith("video/")) {
                    url = "https://graph.facebook.com/v25.0/{page_id}/videos";
                    form.add("title", requestDTO.getTitle());
                    form.add("description", requestDTO.getDescription());
                }

            }
            postIds.add(restClient.post()
                    .uri(url, pageId)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .body(String.class));
        }
        return postIds;
    }

}
