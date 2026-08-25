package com.example.tsldemo.CrossPlatformAPI;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;


import org.apache.tika.Tika;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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

import com.example.tsldemo.Business;
import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.DTOs.Request.CrossPlatPostReqDTO;
import com.example.tsldemo.DTOs.Request.GlobalCrossPlatform.GlobalCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInCredsReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInPostReqDTO;
import com.example.tsldemo.DTOs.Request.LinkedInVideoPostReqDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInAuthRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInImageInitializeUploadRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInUserInfoDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInVideoInitializeUploadRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInVideoStatusRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.LinkedIn.LinkedInVideoUploadInstructionDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaAuthAccessRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaDataUserInfo;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaGranularScopes;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaIdentityRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaPermissionsRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaPostIdRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaPublishStateRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaTokenDetails;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaUserInfoDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.GlobalCredListRespDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.SignInAPI.BusinessRepository;

import jakarta.servlet.http.HttpServletResponse;

@Service
public class CrossPlatformService {

    private static final Logger log = LoggerFactory.getLogger(CrossPlatformService.class);

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

                String reason = "LinkedIn " + response.getStatusCode() + " on " + request.getURI().getPath()
                        + (body.isBlank() ? "" : " — " + body)
                        + (diagnostics.isBlank() ? "" : " [" + diagnostics + "]");

                // Spring logs a ResponseStatusException's reason at DEBUG and (without
                // server.error.include-message) strips it from the response body, so the cause
                // vanishes at both ends. Log it here or it is lost.
                log.error("{}", reason);
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, reason);
            };

    /** Graph's error bodies name the actual problem ("(#200) Requires pages_manage_posts",
     * "Invalid parameter"), which the default handler would throw away. The scheduling paths
     * need it kept: it ends up as the failure reason on the row and in the email telling the
     * user why their post didn't go out, where "502 Bad Gateway" would be useless. */
    private static final RestClient.ResponseSpec.ErrorHandler META_ERROR_HANDLER =
            (request, response) -> {
                String body = StreamUtils.copyToString(response.getBody(), StandardCharsets.UTF_8);
                String reason = "Facebook " + response.getStatusCode() + " on " + request.getURI().getPath()
                        + (body.isBlank() ? "" : " — " + body);

                log.error("{}", reason);
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, reason);
            };

    @Autowired
    private CrossPlatformRepository crossPlatformRepository;
    
    @Autowired
    private BusinessRepository businessRepository;

	private final RestClient restClient;

    @Value("${linkedin.redirect-uri:http://localhost:8081/linkedin/callback}")
    private String linkedInRedirectUri;

    // Must match the Valid OAuth Redirect URI registered on the Meta app, and be identical in
    // the auth request (authCodeMeta) and the token exchange (accessTokenMeta) — so both read it
    // from here. Overridable via META_REDIRECT_URI for non-local deployments.
    @Value("${meta.redirect-uri:http://localhost:8081/meta/callback}")
    private String metaRedirectUri;

    @Value("${frontend.base-url:http://localhost:3000}")
    private String frontendBaseUrl;
    
    @Value("${llm.service.base-url:http://localhost:8080}")
    private String llmServiceBaseUrl;
    
    public CrossPlatformService(RestClient restClient) {
        this.restClient = restClient;
    }

    //////////////////////////////////////////////////////// GLOBAL METHODS ////////////////////////////////////////////////////////
    public List<GlobalCredListRespDTO> getGlobalCredentials(Long businessId, List<PlatformEnum> platforms) {

        List<GlobalCredListRespDTO> globalCredList = new ArrayList<>();
        List<CrossPlatformOAuth> crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatformIn(businessId, platforms);
        for (CrossPlatformOAuth cred : crossPlatformOAuth) {
            GlobalCredListRespDTO globalCredentials = new GlobalCredListRespDTO();
            globalCredentials.setBusinessId(cred.getId());
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
            Business business = checkBusinessExist(cred.businessId());
            crossPlatformOAuth.setBusinessId(business);
            crossPlatformOAuth.setClientId(cred.clientId());
            crossPlatformOAuth.setClientSecret(cred.clientSecret());
            crossPlatformOAuth.setPlatform(cred.platform());

            crossPlatformRepository.save(crossPlatformOAuth);
        }
    }

    public void updateGlobalCredentials(GlobalCredsReqDTO[] creds) {

        for (GlobalCredsReqDTO cred : creds) {
            CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(cred.businessId(), cred.platform());

            // Any stored access token was minted by the OLD app id/secret, so pointing the
            // record at a different developer app invalidates it. Clear it (and the in-flight
            // OAuth state) so the next /auth call re-runs consent instead of no-op'ing on a
            // token the new app can't use.
            if (!Objects.equals(crossPlatformOAuth.getClientId(), cred.clientId())
                    || !Objects.equals(crossPlatformOAuth.getClientSecret(), cred.clientSecret())) {
                crossPlatformOAuth.setAccessToken(null);
                crossPlatformOAuth.setExpiresAt(null);
                crossPlatformOAuth.setState(null);
            }

            crossPlatformOAuth.setClientId(cred.clientId());
            crossPlatformOAuth.setClientSecret(cred.clientSecret());

            crossPlatformRepository.save(crossPlatformOAuth);
        }
    }

    public void deleteGlobalCredentials(Long businessId, List<PlatformEnum> platforms) {
        crossPlatformRepository.deleteByBusinessIdAndPlatformIn(businessId, platforms);
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
        redirectToFrontend(response, "linkedin", connected);
    }

    /** Same as above, but keyed to a specific platform so both LinkedIn and Meta callbacks can
     * bounce the browser back to the Brand Profile with their own status flag
     * (?linkedin=… / ?meta=…). */
    public void redirectToFrontend(HttpServletResponse response, String platform, boolean connected) throws IOException {
        // 0.0.0.0 is a "bind to every interface" address — fine for a server to listen on, but a
        // browser can't navigate to it (ERR_ADDRESS_INVALID). If FRONTEND_BASE_URL was set to it
        // (an easy env slip, since API_HOST uses 0.0.0.0), rewrite the host to localhost so the
        // OAuth round-trip can actually land the user back in the app.
        String baseUrl = frontendBaseUrl.replace("://0.0.0.0", "://localhost");
        response.sendRedirect(baseUrl + "/profile?" + platform + "=" + (connected ? "connected" : "error"));
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
        // See the note in initializeVideoUpload — this URL is signed the same way, so it must
        // not go through RestClient's URI-template encoding.
        uploadClient.put()
                .uri(URI.create(initResp.value().uploadUrl()))
                .contentType(MediaType.parseMediaType(contentType))
                .body(imageBytes)
                .retrieve()
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
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
                // Not a LinkedIn call — labelling it as one would send anyone debugging a
                // failed render off hunting for an auth problem that isn't there.
                .onStatus(HttpStatusCode::isError, (request, response) -> {
                    throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                            "LLM service returned " + response.getStatusCode()
                            + " downloading the rendered video for job " + requestDTO.jobId());
                })
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
            log.error("initializeUpload returned no value block: {}", initResp);
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "LinkedIn did not return upload instructions.");
        }
        String videoUrn = initResp.value().video();
        String uploadToken = initResp.value().uploadToken();

        if (videoUrn == null || uploadToken == null || initResp.value().uploadInstructions() == null) {
            log.error("initializeUpload response incomplete — video={}, uploadToken={}, uploadInstructions={}",
                    videoUrn, uploadToken == null ? "null" : "present", initResp.value().uploadInstructions());
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "LinkedIn's initializeUpload response was missing the video URN, upload token, or upload instructions.");
        }

        List<String> uploadedPartIds = new ArrayList<>();
        for (LinkedInVideoUploadInstructionDTO part : initResp.value().uploadInstructions()) {
            int from = (int) part.firstByte();
            int to = (int) Math.min(part.lastByte(), videoBytes.length - 1);
            byte[] chunk = Arrays.copyOfRange(videoBytes, from, to + 1);

            // URI.create, not the String overload: RestClient treats a String uri as a URI
            // template and re-encodes it, which corrupts the base64 signature LinkedIn puts in
            // this URL's query string and gets the upload rejected as unsigned (401). No
            // Authorization header either — the URL carries its own signature.
            ResponseEntity<Void> putResponse = videoClient.put()
                    .uri(URI.create(part.uploadUrl()))
                    .contentType(MediaType.APPLICATION_OCTET_STREAM)
                    .body(chunk)
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
                    .toBodilessEntity();

            String etag = putResponse.getHeaders().getFirst("ETag");
            if (etag == null) {
                log.error("No ETag on video part upload (bytes {}-{}); response headers were {}",
                        from, to, putResponse.getHeaders().headerNames());
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
                .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
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
            // URI.create keeps the URN encoded exactly once — the String overload would treat
            // the already-encoded value as a template and turn every '%' into '%25', which
            // LinkedIn rejects as an invalid key parameter.
            LinkedInVideoStatusRespDTO status = restClient.get()
                    .uri(URI.create("https://api.linkedin.com/rest/videos/" + encodedUrn))
                    .header("Authorization", "Bearer " + accessToken)
                    .header("LinkedIn-Version", LINKEDIN_API_VERSION)
                    .header("X-Restli-Protocol-Version", "2.0.0")
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, LINKEDIN_ERROR_HANDLER)
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
            Business business = checkBusinessExist(Long.valueOf(businessId));
            crossPlatformOAuth.setBusinessId(business);
            crossPlatformOAuth.setPlatform(PlatformEnum.LINKEDIN);
        }

        crossPlatformOAuth.setClientId(creds.clientId());
        crossPlatformOAuth.setClientSecret(creds.clientSecret());

        crossPlatformRepository.save(crossPlatformOAuth);
    }

    //////////////////////////////////////////////////////// META METHODS ////////////////////////////////////////////////////////
    /** {@code force} re-runs Facebook's consent screen even when a live token is already stored.
     * The Brand Profile passes it because the user clicking "Connect/Reconnect Facebook" has
     * explicitly asked for the dialog — usually to grant a Page the old token never covered. */
    public void authCodeMeta(Long businessId, HttpServletResponse response, boolean force) throws IOException {

        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.META);
        if (crossPlatformOAuth == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                    "No Meta app credentials on file for this business — save the app id/secret first.");
        }

        if (force || crossPlatformOAuth.getAccessToken() == null || crossPlatformOAuth.getExpiresAt() == null || !crossPlatformOAuth.getExpiresAt().isAfter(Instant.now())) {
            String state = UUID.randomUUID().toString();

            String authorizationUrl =
                "https://www.facebook.com/v25.0/dialog/oauth"
                + "?response_type=code"
                + "&client_id=" + URLEncoder.encode(crossPlatformOAuth.getClientId(), StandardCharsets.UTF_8)
                + "&redirect_uri=" + URLEncoder.encode(metaRedirectUri, StandardCharsets.UTF_8)
                + "&state=" + URLEncoder.encode(state, StandardCharsets.UTF_8)
                + "&scope=" + URLEncoder.encode("pages_show_list,pages_manage_posts,pages_read_engagement", StandardCharsets.UTF_8)
                // Without this, a dialog re-run for an account that already granted the scopes
                // short-circuits on "Continue as …" and never re-shows the "What Pages do you
                // want to use with this app?" step — which is exactly the step a user clicking
                // Reconnect needs, since granted scopes with no Page selected yields no Pages.
                + (force ? "&auth_type=rerequest" : "");

            // Persist the state BEFORE redirecting, so the callback can always find it.
            crossPlatformOAuth.setState(state);
            crossPlatformRepository.save(crossPlatformOAuth);

            response.sendRedirect(authorizationUrl);
        } else {
            // Already connected with a live token — send the user straight back into the app.
            // Without this the response is an empty 200 with no Location, which the frontend
            // proxy can only guess at.
            redirectToFrontend(response, "meta", true);
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
                    .queryParam("redirect_uri", metaRedirectUri)
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

        MetaDataUserInfo[] pages = listPostablePages(crossPlatformOAuth);

        // Graph answers "no Pages" with a 200 and an empty data array rather than an error, so
        // without this the UI just renders an empty picker and the user has nothing to act on.
        // Ask Graph what was actually granted and turn it into a message that names the fix.
        if (pages.length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    explainNoPages(crossPlatformOAuth));
        }

        crossPlatformOAuth.setPageIdArray(Arrays.stream(pages).map(MetaDataUserInfo::pageId).toArray(Long[]::new));
        crossPlatformOAuth.setPageNameArray(Arrays.stream(pages).map(MetaDataUserInfo::pageName).toArray(String[]::new));
        crossPlatformRepository.save(crossPlatformOAuth);

        return crossPlatformOAuth;
    }

    /** The Pages this connection can publish to.
     *
     * <p>/me/accounts is the usual source, but it lists Pages by the *account's* own roles and
     * comes back empty for a Page held through a Business portfolio — even when the connection's
     * granular grant explicitly names that Page. The grant is the authority on what the token may
     * act on, so when the account listing is empty, read the granted Pages by id instead. */
    private MetaDataUserInfo[] listPostablePages(CrossPlatformOAuth crossPlatformOAuth) {
        MetaUserInfoDTO metaUserInfo = restClient.get()
            .uri("https://graph.facebook.com/v25.0/me/accounts")
            .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
            .retrieve()
            .body(MetaUserInfoDTO.class);

        if (metaUserInfo != null && metaUserInfo.data() != null && metaUserInfo.data().length > 0) {
            return metaUserInfo.data();
        }

        List<MetaDataUserInfo> granted = new ArrayList<>();
        for (String pageId : pageIdsFromGrant(crossPlatformOAuth)) {
            try {
                MetaDataUserInfo page = restClient.get()
                    .uri("https://graph.facebook.com/v25.0/{pageId}?fields=id,name,access_token", pageId)
                    .header("Authorization", "Bearer " + crossPlatformOAuth.getAccessToken())
                    .retrieve()
                    .body(MetaDataUserInfo.class);

                // No page token means the grant names the Page but Graph won't hand over the
                // credential to act on it — treat it as not connected rather than half-adding it.
                if (page != null && page.pageAccessToken() != null) {
                    granted.add(page);
                }
            } catch (Exception e) {
                log.warn("Granted Facebook Page {} could not be read directly", pageId, e);
            }
        }
        return granted.toArray(MetaDataUserInfo[]::new);
    }

    /** The Page ids the connection's granular grant covers. Empty means either no Page was picked
     * in the consent dialog or the grant covers all Pages — Facebook only lists ids when the user
     * chose specific Pages. */
    private String[] pageIdsFromGrant(CrossPlatformOAuth crossPlatformOAuth) {
        MetaGranularScopes pageScope = pageShowListGrant(crossPlatformOAuth);
        return pageScope == null || pageScope.targetIds() == null ? new String[0] : pageScope.targetIds();
    }

    private MetaGranularScopes pageShowListGrant(CrossPlatformOAuth crossPlatformOAuth) {
        try {
            MetaTokenDetails details = restClient.get()
                .uri("https://graph.facebook.com/debug_token?input_token={token}&access_token={app}",
                        crossPlatformOAuth.getAccessToken(),
                        crossPlatformOAuth.getClientId() + "|" + crossPlatformOAuth.getClientSecret())
                .retrieve()
                .body(MetaTokenDetails.class);

            if (details == null || details.data() == null || details.data().granularScopes() == null) {
                return null;
            }
            return Arrays.stream(details.data().granularScopes())
                    .filter(s -> "pages_show_list".equals(s.scope()))
                    .findFirst()
                    .orElse(null);
        } catch (Exception e) {
            log.warn("Could not read the Meta token's granular scopes", e);
            return null;
        }
    }

    /** Why did /me/accounts come back empty? Almost always one of two things: the consent dialog
     * granted fewer permissions than were asked for, or it granted them while the user picked no
     * Page. /me/permissions distinguishes the two, so the message can name the actual next step
     * instead of leaving the user staring at an empty Page list. */
    private String explainNoPages(CrossPlatformOAuth crossPlatformOAuth) {
        String accessToken = crossPlatformOAuth.getAccessToken();

        // Which account is on the other end of this token? Authorising with a personal profile
        // that doesn't administer the Page looks identical to skipping the Page picker, so name
        // the account and let the user tell the two apart at a glance.
        String connectedAs = "";
        try {
            MetaIdentityRespDTO me = restClient.get()
                .uri("https://graph.facebook.com/v25.0/me?fields=id,name")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .body(MetaIdentityRespDTO.class);

            if (me != null && me.name() != null) {
                connectedAs = "Connected to Facebook as " + me.name() + " (id " + me.id() + "). ";
            }
        } catch (Exception e) {
            log.warn("Could not read the Meta account identity while diagnosing an empty Page list", e);
        }

        List<String> declined = new ArrayList<>();
        try {
            MetaPermissionsRespDTO permissions = restClient.get()
                .uri("https://graph.facebook.com/v25.0/me/permissions")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .body(MetaPermissionsRespDTO.class);

            if (permissions != null && permissions.data() != null) {
                declined = Arrays.stream(permissions.data())
                        .filter(p -> !"granted".equalsIgnoreCase(p.status()))
                        .map(MetaPermissionsRespDTO.MetaPermission::permission)
                        .collect(Collectors.toList());

                List<String> granted = Arrays.stream(permissions.data())
                        .filter(p -> "granted".equalsIgnoreCase(p.status()))
                        .map(MetaPermissionsRespDTO.MetaPermission::permission)
                        .toList();

                for (String required : List.of("pages_show_list", "pages_manage_posts", "pages_read_engagement")) {
                    if (!granted.contains(required) && !declined.contains(required)) {
                        declined.add(required + " (never granted)");
                    }
                }
            }
        } catch (Exception e) {
            // The permissions probe is best-effort — a failure here shouldn't mask the real
            // problem, so fall through to the generic guidance below.
            log.warn("Could not read Meta permissions while diagnosing an empty Page list", e);
        }

        if (!declined.isEmpty()) {
            return connectedAs + "Facebook returned no Pages because these permissions were not granted: "
                    + String.join(", ", declined)
                    + ". Click Reconnect Facebook and accept every permission the dialog asks for.";
        }

        // /me/permissions only reports that pages_show_list was granted — under granular
        // permissions the grant also carries WHICH Pages it covers, and that is the difference
        // between "you skipped the Page picker" and "this account administers no Page at all".
        // Those two need opposite fixes, so ask the grant before guessing.
        MetaGranularScopes pageScope = pageShowListGrant(crossPlatformOAuth);

        // The grant names Pages, yet neither /me/accounts nor a direct read produced a usable
        // Page token (listPostablePages already tried both before we got here).
        if (pageScope != null && pageScope.targetIds() != null && pageScope.targetIds().length > 0) {
            return connectedAs + "Facebook says this connection covers Page(s) "
                    + String.join(", ", pageScope.targetIds())
                    + ", but it will not issue a token to post as them. That points at the Page rather than "
                    + "the consent screen: confirm the account has a Facebook (not just Instagram) admin "
                    + "role with full control of that Page, that the Page is published and not restricted, "
                    + "and — while the Meta app is in Development mode — that the account holds a role on "
                    + "the app itself.";
        }

        if (pageScope != null) {
            return connectedAs + "Facebook granted access to all current and future Pages, yet returned "
                    + "no Pages — so this Facebook account does not administer any Page. Create a Page "
                    + "(facebook.com/pages/create), or reconnect using the account that manages the Page "
                    + "you want to post to, then click Load Pages again.";
        }

        return connectedAs + "Facebook granted the page permissions but returned no Pages. In the consent dialog "
                + "you must also choose which Pages the app may use — click Reconnect Facebook and, on "
                + "the 'What Pages do you want to use with this app?' step, tick your Page (or 'Opt in to "
                + "all current and future Pages'). Also confirm your account has full control of the Page, "
                + "and that it has a role on the Meta app while the app is in Development mode.";
    }

    public List<String> postToMeta(CrossPlatPostReqDTO requestDTO) throws IOException {

        log.info("Meta post requested by business {} for pages {}",
                requestDTO.getBusinessId(), Arrays.toString(requestDTO.getPageId()));

        Map<Long, String> pageTokens = pageTokensFor(
                requireMetaConnected(requestDTO.getBusinessId()), requestDTO.getPageId());

        List<String> postIds = new ArrayList<>();

        for (Map.Entry<Long, String> page : pageTokens.entrySet()) {
            // Body (Form) [No MetaPostReqDTO]
            MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
            form.add("message", requestDTO.getMessage());
            form.add("access_token", page.getValue());

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
                    // This edge captions from `description` — the `message` added above is the
                    // /feed and /photos field and is silently ignored here, so a caller that set
                    // only `message` would publish a video with no caption at all. Fall back to
                    // it rather than letting the caption vanish.
                    form.add("description",
                            requestDTO.getDescription() == null || requestDTO.getDescription().isBlank()
                                    ? requestDTO.getMessage()
                                    : requestDTO.getDescription());
                }

            }
            postIds.add(restClient.post()
                    .uri(url, page.getKey())
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .body(String.class));
        }
        return postIds;
    }

    /** The Meta connection for this business, or a 400 naming the step the user has to do. */
    private CrossPlatformOAuth requireMetaConnected(Long businessId) {
        CrossPlatformOAuth crossPlatformOAuth = crossPlatformRepository
                .findByBusinessIdAndPlatform(businessId, PlatformEnum.META);
        if (crossPlatformOAuth == null || crossPlatformOAuth.getAccessToken() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "This business has not connected Facebook yet — connect it in your Brand Profile first.");
        }
        return crossPlatformOAuth;
    }

    /**
     * Resolves each requested Page to the Page token that can act as it, preserving the order
     * the ids came in — scheduled posts are stored index-aligned against that order, so a later
     * cancel or reschedule can pair each Graph post id back to the Page that holds it.
     */
    private Map<Long, String> pageTokensFor(CrossPlatformOAuth crossPlatformOAuth, Long[] requestedPageIds) {
        if (requestedPageIds == null || requestedPageIds.length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "No Facebook Page was selected — pick a Page in your Brand Profile first.");
        }

        MetaDataUserInfo[] pages = listPostablePages(crossPlatformOAuth);

        // Graph answers "no Pages" with a 200 and an empty data array. Posting then died on an
        // ArrayIndexOutOfBounds while looking up the Page token, which reached the browser as a
        // bare 500 that said nothing about the actual problem — the same empty-Page-list state
        // the Brand Profile already explains. Reuse that explanation here.
        if (pages.length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    explainNoPages(crossPlatformOAuth));
        }

        Map<Long, String> pageTokens = new LinkedHashMap<>();
        for (Long pageId : requestedPageIds) {
            // Publishing to a Page uses that Page's own token, not the user token, so a Page the
            // current token no longer covers (revoked, or a stale id cached in the browser) has
            // to be named — otherwise the user has no way to tell which selection went bad.
            pageTokens.put(pageId, Arrays.stream(pages)
                    .filter(page -> Objects.equals(page.pageId(), pageId))
                    .map(MetaDataUserInfo::pageAccessToken)
                    .findFirst()
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST,
                            "Facebook Page " + pageId + " is not one this connection can post to. "
                            + "Pages available on the current connection: "
                            + Arrays.stream(pages)
                                    .map(p -> p.pageName() + " (" + p.pageId() + ")")
                                    .collect(Collectors.joining(", "))
                            + ". Reload the Page list in your Brand Profile and pick one of these.")));
        }
        return pageTokens;
    }

    //////////////////////////////////////////////////////// META SCHEDULING ////////////////////////////////////////////////////////

    /**
     * Hands the schedule to Facebook rather than holding it ourselves.
     *
     * <p>An unpublished post with a {@code scheduled_publish_time} is Graph's own scheduling
     * primitive: Facebook stores it and publishes it at that moment whether or not this service
     * is running. That is strictly better than a server-side timer for the one platform that
     * offers it — there is no window in which our downtime loses the post — so LinkedIn is the
     * only platform left that actually needs the sweeper to publish it.
     *
     * <p>Callers must check the 10-minute/6-month lead-time bounds first; Graph rejects anything
     * outside them, and {@code ScheduledPostService} falls back to the sweeper in that case.
     *
     * @return one Graph post id per Page, in the same order as {@code pageIds}
     */
    public List<String> scheduleToMeta(Long businessId, Long[] pageIds, String message, Instant publishAt) {
        Map<Long, String> pageTokens = pageTokensFor(requireMetaConnected(businessId), pageIds);
        List<String> postIds = new ArrayList<>();

        for (Map.Entry<Long, String> page : pageTokens.entrySet()) {
            MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
            form.add("message", message);
            form.add("published", "false");
            form.add("scheduled_publish_time", String.valueOf(publishAt.getEpochSecond()));
            form.add("access_token", page.getValue());

            MetaPostIdRespDTO created = restClient.post()
                    .uri("https://graph.facebook.com/v25.0/{page_id}/feed", page.getKey())
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, META_ERROR_HANDLER)
                    .body(MetaPostIdRespDTO.class);

            if (created == null || created.id() == null) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                        "Facebook accepted the scheduled post for Page " + page.getKey()
                        + " but returned no post id, so it could not be tracked. Check the Page's "
                        + "scheduled posts in Meta Business Suite before trying again.");
            }
            postIds.add(created.id());
        }

        log.info("Scheduled {} Facebook post(s) for business {} at {}", postIds.size(), businessId, publishAt);
        return postIds;
    }

    /** Publishes text to each Page immediately. Used by the sweeper for the posts Graph would
     * not take a native schedule for (under its 10-minute lead time). */
    public List<String> publishTextToMeta(Long businessId, Long[] pageIds, String message) {
        Map<Long, String> pageTokens = pageTokensFor(requireMetaConnected(businessId), pageIds);
        List<String> postIds = new ArrayList<>();

        for (Map.Entry<Long, String> page : pageTokens.entrySet()) {
            MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
            form.add("message", message);
            form.add("access_token", page.getValue());

            MetaPostIdRespDTO created = restClient.post()
                    .uri("https://graph.facebook.com/v25.0/{page_id}/feed", page.getKey())
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, META_ERROR_HANDLER)
                    .body(MetaPostIdRespDTO.class);

            postIds.add(created == null || created.id() == null ? "" : created.id());
        }
        return postIds;
    }

    /** Deletes posts Facebook is holding for a future time, so cancelling in the calendar
     * actually stops the post rather than only hiding it from our own table. */
    public void cancelScheduledMetaPosts(Long businessId, Long[] pageIds, String[] postIds) {
        if (postIds == null || postIds.length == 0) {
            return;
        }
        List<String> tokens = new ArrayList<>(
                pageTokensFor(requireMetaConnected(businessId), pageIds).values());

        for (int i = 0; i < postIds.length; i++) {
            restClient.delete()
                    .uri("https://graph.facebook.com/v25.0/{postId}", postIds[i])
                    .header("Authorization", "Bearer " + tokenAt(tokens, i))
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, META_ERROR_HANDLER)
                    .toBodilessEntity();
        }
        log.info("Deleted {} scheduled Facebook post(s) for business {}", postIds.length, businessId);
    }

    /** Moves a Facebook-held schedule to a new time. */
    public void rescheduleMetaPosts(Long businessId, Long[] pageIds, String[] postIds, Instant publishAt) {
        editScheduledMetaPosts(businessId, pageIds, postIds,
                "scheduled_publish_time", String.valueOf(publishAt.getEpochSecond()));
    }

    /** Rewrites the copy of a Facebook-held schedule. */
    public void updateScheduledMetaPosts(Long businessId, Long[] pageIds, String[] postIds, String message) {
        editScheduledMetaPosts(businessId, pageIds, postIds, "message", message);
    }

    private void editScheduledMetaPosts(Long businessId, Long[] pageIds, String[] postIds,
                                        String field, String value) {
        if (postIds == null || postIds.length == 0) {
            return;
        }
        List<String> tokens = new ArrayList<>(
                pageTokensFor(requireMetaConnected(businessId), pageIds).values());

        for (int i = 0; i < postIds.length; i++) {
            MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
            form.add(field, value);
            form.add("access_token", tokenAt(tokens, i));

            restClient.post()
                    .uri("https://graph.facebook.com/v25.0/{postId}", postIds[i])
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .onStatus(HttpStatusCode::isError, META_ERROR_HANDLER)
                    .toBodilessEntity();
        }
    }

    /**
     * Confirms posts Facebook was holding actually went live.
     *
     * @return null when every post is published, otherwise a description of what is not — which
     *         becomes the failure reason on the row and in the user's email
     */
    public String verifyMetaPostsPublished(Long businessId, Long[] pageIds, String[] postIds) {
        if (postIds == null || postIds.length == 0) {
            return "Facebook never returned a post id for this schedule, so it cannot be confirmed "
                    + "as published. Check the Page's scheduled posts in Meta Business Suite.";
        }
        List<String> tokens = new ArrayList<>(
                pageTokensFor(requireMetaConnected(businessId), pageIds).values());

        List<String> problems = new ArrayList<>();
        for (int i = 0; i < postIds.length; i++) {
            try {
                MetaPublishStateRespDTO state = restClient.get()
                        .uri("https://graph.facebook.com/v25.0/{postId}?fields=is_published", postIds[i])
                        .header("Authorization", "Bearer " + tokenAt(tokens, i))
                        .retrieve()
                        .onStatus(HttpStatusCode::isError, META_ERROR_HANDLER)
                        .body(MetaPublishStateRespDTO.class);

                if (state == null || !Boolean.TRUE.equals(state.isPublished())) {
                    problems.add(postIds[i] + " is still unpublished");
                }
            } catch (Exception e) {
                problems.add(postIds[i] + " could not be checked (" + e.getMessage() + ")");
            }
        }

        return problems.isEmpty() ? null
                : "Facebook did not confirm this post went live: " + String.join("; ", problems) + ".";
    }

    /** Post ids are stored in the same order as their Pages, so index i is Page i's token. The
     * fallback only matters if a stored row predates that guarantee or lost a Page. */
    private static String tokenAt(List<String> tokens, int index) {
        return index < tokens.size() ? tokens.get(index) : tokens.get(0);
    }

    public Business checkBusinessExist(Long businessId) {
        Business business = businessRepository.findById(businessId);
        if (business == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Business not found with ID: " + businessId);
        }
        return business;
    }
}
