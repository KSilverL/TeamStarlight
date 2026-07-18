package com.example.tsldemo.CrossPlatformAPI;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;

import org.springframework.beans.factory.annotation.*;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
import com.example.tsldemo.DTOs.Request.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInAuthRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInUserInfoDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.SessionAPI.SessionService;

import jakarta.servlet.http.HttpServletResponse;

@Service
public class CrossPlatformService {

    @Autowired
    private CrossPlatformRepository crossPlatformRepository;
    
    @Autowired SessionService sessionServ;

	private final RestClient restClient;

    @Value("${linkedin.redirect-uri:http://localhost:8081/linkedin/callback}")
    private String linkedInRedirectUri;

    @Value("${frontend.base-url:http://localhost:3000}")
    private String frontendBaseUrl;
    
    private final TaskScheduler taskScheduler;

    public CrossPlatformService(RestClient restClient, TaskScheduler taskScheduler) {
        this.restClient = restClient;
        this.taskScheduler = taskScheduler;
    }

    public void authCodeLinkedIn(int businessId, HttpServletResponse response) throws IOException {
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.LINKEDIN);
        if (crossPlatformOAuth == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "No LinkedIn app credentials on file for this business — call /linkedin/addCompCreds first.");
        }

        if (crossPlatformOAuth.getAccessToken() == null || crossPlatformOAuth.getExpiresAt() == null || !crossPlatformOAuth.getExpiresAt().isAfter(Instant.now())) {
            String state = UUID.randomUUID().toString();

            String authorizationUrl =
                "https://www.linkedin.com/oauth/v2/authorization"
                + "?response_type=code"
                + "&client_id=" + URLEncoder.encode(crossPlatformOAuth.getClientId(), StandardCharsets.UTF_8)
                + "&redirect_uri=" + URLEncoder.encode(linkedInRedirectUri, StandardCharsets.UTF_8)
                + "&state=" + URLEncoder.encode(state, StandardCharsets.UTF_8)
                + "&scope=" + URLEncoder.encode("openid profile email w_member_social", StandardCharsets.UTF_8);

            // Persist the state BEFORE redirecting, so the callback can always find it.
            crossPlatformOAuth.setState(state);
            crossPlatformRepository.save(crossPlatformOAuth);

            response.sendRedirect(authorizationUrl);
        } else {
            // Already connected with a live token — send the user straight back into the app.
            redirectToFrontend(response, true);
        }
    }

    public LinkedInAuthRespDTO accessTokenLinkedIn(String authorizationCode, String state) {
        RestClient restClient = RestClient.create();

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByStateAndPlatform(state, PlatformEnum.LINKEDIN);
        if (crossPlatformOAuth == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown or expired LinkedIn OAuth state.");
        }

        MultiValueMap<String, String> form = new LinkedMultiValueMap<>();
        form.add("grant_type", "authorization_code");
        form.add("code", authorizationCode);
        form.add("redirect_uri", linkedInRedirectUri);
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

    /** Sends the browser's top-level navigation back into the frontend app after the OAuth
     * round-trip finishes (success or failure) — the callback is hit directly by LinkedIn, so
     * this is the user's only way back into the SPA. */
    public void redirectToFrontend(HttpServletResponse response, boolean connected) throws IOException {
        response.sendRedirect(frontendBaseUrl + "/profile?linkedin=" + (connected ? "connected" : "error"));
    }

    public String postToLinkedIn(int businessId, LinkedInPostReqDTO requestDTO) {

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.LINKEDIN);
        if (crossPlatformOAuth == null || crossPlatformOAuth.getAccessToken() == null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "LinkedIn isn't connected for this business yet.");
        }

        LinkedInUserInfoDTO linkedInUserInfo = restClient.get()
                .uri("https://api.linkedin.com/v2/userinfo")
                .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
                .retrieve()
                .body(LinkedInUserInfoDTO.class);

        Map<String, Object> requestBody = Map.of(
                "author", "urn:li:person:" + linkedInUserInfo.sub(),
                "commentary", requestDTO.message(),
                "visibility", "PUBLIC",
                "distribution", Map.of(
                        "feedDistribution", "MAIN_FEED",
                        "targetEntities", List.of(),
                        "thirdPartyDistributionChannels", List.of()
                ),
                "lifecycleState", "PUBLISHED",
                "isReshareDisabledByAuthor", false
        );

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

    public void saveLinkedInCredentials(int businessId, LinkedInCredsReqDTO creds) {
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.LINKEDIN);
        if (crossPlatformOAuth == null) {
            crossPlatformOAuth = new CrossPlatformOAuth();
            crossPlatformOAuth.setBusinessId(businessId);
            crossPlatformOAuth.setPlatform(PlatformEnum.LINKEDIN);
        }

        crossPlatformOAuth.setClientId(creds.clientId());
        crossPlatformOAuth.setClientSecret(creds.clientSecret());

        crossPlatformRepository.save(crossPlatformOAuth);
    }
    
    public void schedulePostToLinkedIn(int businessId, LinkedInPostReqDTO scheduledPost) {
        Instant when = scheduledPost.scheduledTime()
                .atZone(ZoneId.systemDefault())
                .toInstant();

        taskScheduler.schedule(() -> {
            System.out.println("Scheduled LinkedIn post fired at " + Instant.now());
            postToLinkedIn(businessId, scheduledPost);
        }, when);
    }
    
}
