package com.example.tsldemo.CrossPlatformAPI;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

import org.apache.tika.Tika;
import org.springframework.beans.factory.annotation.*;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.DTOs.Request.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInVideoPostReqDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInAuthRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInImageInitializeUploadRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInUserInfoDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInVideoInitializeUploadRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInVideoStatusRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInVideoUploadInstructionDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;

import jakarta.servlet.http.HttpServletResponse;

@Service
public class CrossPlatformService {

    // Every LinkedIn REST call (posts, images, videos, oauth userinfo) is versioned the same way.
    private static final String LINKEDIN_API_VERSION = "202606";

    // The one scope that separates a token that can publish from one that can only sign in.
    private static final String POSTING_SCOPE = "w_member_social";

    // LinkedIn's own stated bounds for an organic video upload (Videos API docs).
    private static final long MIN_VIDEO_BYTES = 75L * 1024;
    private static final long MAX_VIDEO_BYTES = 500L * 1024 * 1024;

    // How long to wait for LinkedIn to finish processing an uploaded video before giving up.
    private static final Duration VIDEO_PROCESSING_TIMEOUT = Duration.ofSeconds(90);
    private static final Duration VIDEO_PROCESSING_POLL_INTERVAL = Duration.ofSeconds(2);

    /** Turns a failed LinkedIn call into an exception that actually says what went wrong.
     * LinkedIn commonly answers /rest/* with a bodiless 401 and puts the real reason in its
     * x-li-* diagnostic headers, which the default handler discards. */
    private static final RestClient.ResponseSpec.ErrorHandler LINKEDIN_ERROR_HANDLER =
            (request, response) -> {
                String body = StreamUtils.copyToString(response.getBody(), StandardCharsets.UTF_8);
                String diagnostics = response.getHeaders().headerSet().stream()
                        .filter(e -> e.getKey().toLowerCase().startsWith("x-li-"))
                        .map(e -> e.getKey() + "=" + String.join(",", e.getValue()))
                        .collect(Collectors.joining("; "));

                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                        "LinkedIn " + response.getStatusCode() + " on " + request.getURI().getPath()
                        + (body.isBlank() ? "" : " — " + body)
                        + (diagnostics.isBlank() ? "" : " [" + diagnostics + "]"));
            };

    @Autowired
    private CrossPlatformRepository crossPlatformRepository;

	private final RestClient restClient;

    @Value("${linkedin.redirect-uri:http://localhost:8081/linkedin/callback}")
    private String linkedInRedirectUri;

    @Value("${frontend.base-url:http://localhost:3000}")
    private String frontendBaseUrl;

    @Value("${llm.service.base-url:http://localhost:8080}")
    private String llmServiceBaseUrl;

    public CrossPlatformService(RestClient restClient) {
        this.restClient = restClient;
    }

    //////////////////////////////////////////////////////// LINKEDIN METHODS ////////////////////////////////////////////////////////
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

        // LinkedIn drops requested scopes the app's products don't authorize instead of failing
        // the exchange, so a sign-in-only token looks perfectly valid here and only breaks later
        // with a bodiless 401 from /rest/*. Catch it now, while we can still name the cause.
        String grantedScopes = token.scope() == null ? "" : token.scope();
        if (!grantedScopes.contains(POSTING_SCOPE)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "LinkedIn granted only [" + grantedScopes + "] — the '" + POSTING_SCOPE
                    + "' scope is missing, so this token can sign in but cannot post. Add the "
                    + "'Share on LinkedIn' product to the LinkedIn app, then reconnect.");
        }

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

    /** The author URN every post/upload is attributed to — resolved fresh each call since the
     * access token can rotate between calls. */
    private String getAuthorUrn(String accessToken) {
        LinkedInUserInfoDTO linkedInUserInfo = restClient.get()
                .uri("https://api.linkedin.com/v2/userinfo")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
                .body(LinkedInUserInfoDTO.class);
        return "urn:li:person:" + linkedInUserInfo.sub();
    }

    private CrossPlatformOAuth requireConnected(int businessId) {
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.LINKEDIN);
        if (crossPlatformOAuth == null || crossPlatformOAuth.getAccessToken() == null) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "LinkedIn isn't connected for this business yet.");
        }
        return crossPlatformOAuth;
    }

    public String postToLinkedIn(int businessId, LinkedInPostReqDTO requestDTO) {
        CrossPlatformOAuth crossPlatformOAuth = requireConnected(businessId);
        String authorUrn = getAuthorUrn(crossPlatformOAuth.getAccessToken());

        Map<String, Object> requestBody = Map.of(
                "author", authorUrn,
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
                .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(requestBody)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
                .toBodilessEntity();

        return response.getHeaders().getFirst("x-restli-id");
    }

    /** Uploads a user-attached image to LinkedIn's Images API and publishes a post referencing
     * it. Images (unlike videos) upload in a single PUT — no chunking, no processing wait — so
     * this is a short, fully-synchronous round-trip. */
    public String postImageToLinkedIn(int businessId, String message, MultipartFile image) {
        CrossPlatformOAuth crossPlatformOAuth = requireConnected(businessId);
        String accessToken = crossPlatformOAuth.getAccessToken();
        String authorUrn = getAuthorUrn(accessToken);

        byte[] imageBytes;
        try {
            imageBytes = image.getBytes();
        } catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Could not read the uploaded image.");
        }
        if (imageBytes.length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "The uploaded image is empty.");
        }
        // Trust a content sniff over the client-declared type — LinkedIn rejects a mismatch.
        String contentType = new Tika().detect(imageBytes);
        if (contentType == null || !contentType.startsWith("image/")) {
            throw new ResponseStatusException(HttpStatus.UNSUPPORTED_MEDIA_TYPE,
                    "Only image files can be posted through this endpoint.");
        }

        String imageUrn = uploadImage(authorUrn, accessToken, imageBytes, contentType);
        return publishImagePost(authorUrn, accessToken, imageUrn, message);
    }

    /** Registers the image upload, PUTs the bytes to the returned upload URL, and returns the
     * resulting image URN. */
    private String uploadImage(String authorUrn, String accessToken, byte[] imageBytes, String contentType) {
        Map<String, Object> initBody = Map.of(
                "initializeUploadRequest", Map.of("owner", authorUrn)
        );
        LinkedInImageInitializeUploadRespDTO initResp = restClient.post()
                .uri("https://api.linkedin.com/rest/images?action=initializeUpload")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + accessToken)
                .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(initBody)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
                .body(LinkedInImageInitializeUploadRespDTO.class);
        if (initResp == null || initResp.value() == null || initResp.value().uploadUrl() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "LinkedIn did not return image upload instructions.");
        }

        // A separate, un-instrumented client — the shared `restClient` bean's request
        // interceptor logs every request body as a String, which would try to stringify the
        // raw image bytes.
        RestClient uploadClient = RestClient.create();
        uploadClient.put()
                .uri(initResp.value().uploadUrl())
                .contentType(MediaType.parseMediaType(contentType))
                .body(imageBytes)
                .retrieve()
                .toBodilessEntity();

        return initResp.value().image();
    }

    private String publishImagePost(String authorUrn, String accessToken, String imageUrn, String message) {
        Map<String, Object> requestBody = Map.of(
                "author", authorUrn,
                "commentary", message == null ? "" : message,
                "visibility", "PUBLIC",
                "distribution", Map.of(
                        "feedDistribution", "MAIN_FEED",
                        "targetEntities", List.of(),
                        "thirdPartyDistributionChannels", List.of()
                ),
                "content", Map.of("media", Map.of("id", imageUrn)),
                "lifecycleState", "PUBLISHED",
                "isReshareDisabledByAuthor", false
        );

        ResponseEntity<Void> response = restClient.post()
                .uri("https://api.linkedin.com/rest/posts")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + accessToken)
                .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(requestBody)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
                .toBodilessEntity();

        return response.getHeaders().getFirst("x-restli-id");
    }

    /** Uploads the rendered MP4 for a finished video job to LinkedIn's Videos API, waits for
     * LinkedIn to finish processing it, then publishes a post referencing it. Runs entirely
     * synchronously — LinkedIn's own processing of a short clip is normally a few seconds, and
     * this mirrors the existing immediate-publish behaviour of {@link #postToLinkedIn}. */
    public String postVideoToLinkedIn(int businessId, LinkedInVideoPostReqDTO requestDTO) {
        CrossPlatformOAuth crossPlatformOAuth = requireConnected(businessId);
        String accessToken = crossPlatformOAuth.getAccessToken();
        String authorUrn = getAuthorUrn(accessToken);

        // A separate, un-instrumented client — the shared `restClient` bean's request
        // interceptor (RestClientConfig) logs every request body as a String, which would try
        // to stringify a multi-MB binary on the video download and every chunk upload below.
        RestClient videoClient = RestClient.create();

        byte[] videoBytes = videoClient.get()
                .uri(llmServiceBaseUrl + "/video-jobs/" + requestDTO.jobId() + "/download")
                .retrieve()
                .body(byte[].class);
        if (videoBytes == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "Could not fetch the rendered video for job " + requestDTO.jobId());
        }
        if (videoBytes.length < MIN_VIDEO_BYTES || videoBytes.length > MAX_VIDEO_BYTES) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_CONTENT,
                    "Rendered video is " + videoBytes.length + " bytes — outside LinkedIn's 75KB-500MB limit.");
        }

        String videoUrn = initializeVideoUpload(authorUrn, accessToken, videoBytes, videoClient);
        waitUntilVideoAvailable(videoUrn, accessToken);
        return publishVideoPost(authorUrn, accessToken, videoUrn, requestDTO);
    }

    /** Registers the upload, PUTs every byte-range chunk LinkedIn asks for (collecting each
     * response's ETag, in order), and finalizes — returning the resulting video URN. */
    private String initializeVideoUpload(String authorUrn, String accessToken, byte[] videoBytes, RestClient videoClient) {
        Map<String, Object> initBody = Map.of(
                "initializeUploadRequest", Map.of(
                        "owner", authorUrn,
                        "fileSizeBytes", videoBytes.length,
                        "uploadCaptions", false,
                        "uploadThumbnail", false
                )
        );
        LinkedInVideoInitializeUploadRespDTO initResp = restClient.post()
                .uri("https://api.linkedin.com/rest/videos?action=initializeUpload")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + accessToken)
                .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(initBody)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
                .body(LinkedInVideoInitializeUploadRespDTO.class);
        if (initResp == null || initResp.value() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "LinkedIn did not return upload instructions.");
        }
        String videoUrn = initResp.value().video();
        String uploadToken = initResp.value().uploadToken();

        List<String> uploadedPartIds = new ArrayList<>();
        for (LinkedInVideoUploadInstructionDTO part : initResp.value().uploadInstructions()) {
            int from = (int) part.firstByte();
            int to = (int) Math.min(part.lastByte(), videoBytes.length - 1);
            byte[] chunk = Arrays.copyOfRange(videoBytes, from, to + 1);

            ResponseEntity<Void> putResponse = videoClient.put()
                    .uri(part.uploadUrl())
                    .contentType(MediaType.APPLICATION_OCTET_STREAM)
                    .body(chunk)
                    .retrieve()
                    .toBodilessEntity();

            String etag = putResponse.getHeaders().getFirst("ETag");
            if (etag == null) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                        "LinkedIn did not return an ETag for an uploaded video part.");
            }
            uploadedPartIds.add(etag.replace("\"", ""));
        }

        Map<String, Object> finalizeBody = Map.of(
                "finalizeUploadRequest", Map.of(
                        "video", videoUrn,
                        "uploadToken", uploadToken,
                        "uploadedPartIds", uploadedPartIds
                )
        );
        restClient.post()
                .uri("https://api.linkedin.com/rest/videos?action=finalizeUpload")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + accessToken)
                .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(finalizeBody)
                .retrieve()
                .toBodilessEntity();

        return videoUrn;
    }

    /** Blocks (on the request thread — see the class-level note on the synchronous design)
     * until LinkedIn reports the uploaded video as AVAILABLE, or gives up after
     * {@link #VIDEO_PROCESSING_TIMEOUT}. */
    private void waitUntilVideoAvailable(String videoUrn, String accessToken) {
        String encodedUrn = URLEncoder.encode(videoUrn, StandardCharsets.UTF_8);
        Instant deadline = Instant.now().plus(VIDEO_PROCESSING_TIMEOUT);

        while (true) {
            LinkedInVideoStatusRespDTO status = restClient.get()
                    .uri("https://api.linkedin.com/rest/videos/" + encodedUrn)
                    .header("Authorization", "Bearer " + accessToken)
                    .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                    .header("X-Restli-Protocol-Version", "2.0.0")
                    .retrieve()
                    .body(LinkedInVideoStatusRespDTO.class);

            if (status != null && "AVAILABLE".equals(status.status())) {
                return;
            }
            if (status != null && "PROCESSING_FAILED".equals(status.status())) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                        "LinkedIn failed to process the video: " + status.processingFailureReason());
            }
            if (Instant.now().isAfter(deadline)) {
                throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT,
                        "LinkedIn is still processing the video — try posting again shortly.");
            }
            try {
                Thread.sleep(VIDEO_PROCESSING_POLL_INTERVAL.toMillis());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                        "Interrupted while waiting for LinkedIn to process the video.");
            }
        }
    }

    private String publishVideoPost(String authorUrn, String accessToken, String videoUrn, LinkedInVideoPostReqDTO requestDTO) {
        Map<String, Object> media = requestDTO.title() != null && !requestDTO.title().isBlank()
                ? Map.of("id", videoUrn, "title", requestDTO.title())
                : Map.of("id", videoUrn);

        Map<String, Object> requestBody = Map.of(
                "author", authorUrn,
                "commentary", requestDTO.message(),
                "visibility", "PUBLIC",
                "distribution", Map.of(
                        "feedDistribution", "MAIN_FEED",
                        "targetEntities", List.of(),
                        "thirdPartyDistributionChannels", List.of()
                ),
                "content", Map.of("media", media),
                "lifecycleState", "PUBLISHED",
                "isReshareDisabledByAuthor", false
        );

        ResponseEntity<Void> response = restClient.post()
                .uri("https://api.linkedin.com/rest/posts")
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + accessToken)
                .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                .header("X-Restli-Protocol-Version", "2.0.0")
                .body(requestBody)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
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

}
