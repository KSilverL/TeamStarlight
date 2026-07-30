package com.example.tsldemo.CrossPlatformAPI;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;

import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;
import java.util.ArrayList;
import java.util.Arrays;
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
import org.springframework.scheduling.TaskScheduler;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.util.StreamUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.Message;
import com.example.tsldemo.Session;
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
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaDataTokenDetails;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaDataUserInfo;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaGranularScopes;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaIdentityRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaInstagramAccount;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaPageInstagramRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaPermissionsRespDTO;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaTokenDetails;
import com.example.tsldemo.DTOs.ResponseReceived.Meta.MetaUserInfoDTO;
import com.example.tsldemo.DTOs.ResponseToFrontEnd.GlobalCredListRespDTO;
import com.example.tsldemo.ENUMS.PlatformEnum;
import com.example.tsldemo.SessionAPI.SessionService;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

import jakarta.servlet.http.HttpServletResponse;

@Service
public class CrossPlatformService {

    private static final Logger log = LoggerFactory.getLogger(CrossPlatformService.class);

    // Every LinkedIn REST call (posts, images, videos, oauth userinfo) is versioned the same way.
    private static final String LINKEDIN_API_VERSION = "202606";

    // The one scope that separates a token that can publish from one that can only sign in.
    private static final String POSTING_SCOPE = "w_member_social";

    /** Meta permissions requested at consent. Instagram publishing rides on the Facebook Page
     * connection rather than a separate login: instagram_basic resolves the Page's linked
     * Instagram account, instagram_content_publish allows creating and publishing media on it.
     *
     * Single source of truth on purpose — the consent URL and the "why did I get no Pages"
     * diagnostic both read this list, and they previously each hardcoded their own copy, so a
     * scope added for publishing would not have been reported as missing when it was declined. */
    private static final List<String> META_SCOPES = List.of(
            "pages_show_list",
            "pages_manage_posts",
            "pages_read_engagement",
            "instagram_basic",
            "instagram_content_publish");

    /** Fields to request on the /me/accounts edge. instagram_business_account is NOT in Graph's
     * default field set, so it has to be named explicitly — and naming any field at all replaces
     * the default set, hence the others are respelled here rather than being inherited. */
    private static final String META_PAGE_FIELDS =
            "id,name,access_token,category,category_list,tasks,instagram_business_account{id,username}";

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

    @Autowired
    private CrossPlatformRepository crossPlatformRepository;
    
    @Autowired SessionService sessionServ;

	private final RestClient restClient;

    // Used where a Graph response is read as text before being parsed, so the raw JSON can be
    // logged for diagnosis. Constructed rather than injected, as elsewhere in this codebase —
    // Boot 4 auto-configures the Jackson 3 mapper and there is no Jackson 2 bean to inject.
    private final ObjectMapper objectMapper = new ObjectMapper();

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
    
    private final TaskScheduler taskScheduler;


    public CrossPlatformService(RestClient restClient, TaskScheduler taskScheduler) {
        this.restClient = restClient;
        this.taskScheduler = taskScheduler;
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
            crossPlatformOAuth.setBusinessId((long) businessId);
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
                + "&scope=" + URLEncoder.encode(String.join(",", META_SCOPES), StandardCharsets.UTF_8);

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

        System.out.println("Start Post Method");
        System.out.println("PageId not found, retrieving data");
        MetaUserInfoDTO metaUserInfo = fetchMetaPages(crossPlatformOAuth.getAccessToken());

        // Graph answers "no Pages" with a 200 and an empty data array rather than an error, so
        // without this the UI just renders an empty picker and the user has nothing to act on.
        // Ask Graph what was actually granted and turn it into a message that names the fix.
        if (metaUserInfo == null || metaUserInfo.data() == null || metaUserInfo.data().length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    explainNoPages(crossPlatformOAuth));
        }

        crossPlatformOAuth.setPageIdArray(Arrays.stream(metaUserInfo.data()).map(MetaDataUserInfo::pageId).toArray(Long[]::new));
        crossPlatformOAuth.setPageNameArray(Arrays.stream(metaUserInfo.data()).map(MetaDataUserInfo::pageName).toArray(String[]::new));
        // Index-aligned with the two arrays above, null where a Page has no Instagram account
        // linked. Stored so the Brand Profile can show which Pages can carry an Instagram post
        // without re-querying Graph; the id is still re-resolved at publish time, since the user
        // can link or unlink an account at any point after connecting.
        crossPlatformOAuth.setIgUserIdArray(Arrays.stream(metaUserInfo.data())
                .map(page -> page.instagramBusinessAccount() == null
                        ? null
                        : page.instagramBusinessAccount().igUserId())
                .toArray(String[]::new));
        crossPlatformRepository.save(crossPlatformOAuth);

        return crossPlatformOAuth;
    }

    /** Null when at least one Page resolved an Instagram account, otherwise a message naming the
     * step to take. Kept separate from the Page list itself because having no Instagram account is
     * not an error — the Pages are still usable for Facebook posting, so this is advice, not a
     * failure, and must not stop the picker from rendering. */
    public String instagramNoticeFor(Long businessId) {
        CrossPlatformOAuth oauth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.META);
        if (oauth == null || oauth.getAccessToken() == null || oauth.getIgUserIdArray() == null) {
            return null;
        }
        boolean anyLinked = Arrays.stream(oauth.getIgUserIdArray()).anyMatch(Objects::nonNull);
        return anyLinked ? null : explainNoInstagram(oauth.getAccessToken());
    }

    /** One publishable Instagram account: which account to address, and the Page token that
     * authorises it. Page tokens are short-lived and never stored, so this is only ever built
     * fresh from Graph and used immediately. */
    public record InstagramTarget(Long pageId, String pageName, String igUserId, String username,
                                 String pageAccessToken) {}

    /** Resolves the Instagram accounts reachable from the given Pages, for this business only.
     *
     * The businessId comes from the caller's JWT, and the Pages are looked up under that
     * business's own Meta connection — so naming another business's Page id here resolves
     * nothing rather than posting to it.
     *
     * Fails with a message naming the actual next step rather than returning an empty list,
     * because every empty case has a different fix: no Meta connection at all, a Page that isn't
     * administered by this token, or a Page with no Instagram account linked to it. */
    public List<InstagramTarget> resolveInstagramTargets(long businessId, List<Long> pageIds) {
        if (pageIds == null || pageIds.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "No Facebook Page selected. Pick a Page in your Brand Profile — an Instagram post "
                    + "is published through the Page its account is linked to.");
        }

        CrossPlatformOAuth oauth = crossPlatformRepository.findByBusinessIdAndPlatform(businessId, PlatformEnum.META);
        if (oauth == null || oauth.getAccessToken() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Facebook is not connected for this business. Connect Facebook from your Brand "
                    + "Profile first — Instagram publishing uses that connection.");
        }

        MetaUserInfoDTO pages = fetchMetaPages(oauth.getAccessToken());
        if (pages == null || pages.data() == null || pages.data().length == 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, explainNoPages(oauth));
        }

        List<InstagramTarget> targets = new ArrayList<>();
        List<String> unlinked = new ArrayList<>();
        for (Long pageId : pageIds) {
            MetaDataUserInfo page = Arrays.stream(pages.data())
                    .filter(p -> Objects.equals(p.pageId(), pageId))
                    .findFirst()
                    .orElse(null);

            if (page == null) {
                // Either the id isn't this business's Page, or consent no longer covers it.
                // Both are the user's to fix, and neither should leak whose Page it might be.
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "Facebook Page " + pageId + " is not available on this connection. Reconnect "
                        + "Facebook and make sure that Page is ticked in the consent dialog.");
            }
            if (page.instagramBusinessAccount() == null) {
                unlinked.add(page.pageName() == null ? String.valueOf(pageId) : page.pageName());
                continue;
            }
            targets.add(new InstagramTarget(
                    page.pageId(),
                    page.pageName(),
                    page.instagramBusinessAccount().igUserId(),
                    page.instagramBusinessAccount().username(),
                    page.pageAccessToken()));
        }

        if (targets.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "No Instagram account is linked to " + String.join(", ", unlinked) + ". In Meta "
                    + "Business Suite, link an Instagram professional (Business or Creator) account to "
                    + "the Page, then reconnect Facebook here. Personal Instagram accounts cannot be "
                    + "published to through the API.");
        }
        return targets;
    }

    /** The Pages this token administers, with the Page access token and linked Instagram account
     * for each. Both the connect flow and every publish path need exactly this, and the Page
     * access tokens are deliberately never persisted — they are re-read here each time so a
     * token revoked or rotated on Meta's side can't be used from stale local state. */
    private MetaUserInfoDTO fetchMetaPages(String userAccessToken) {
        // Handed to RestClient as a finished URI rather than through a UriBuilder, because
        // META_PAGE_FIELDS uses Graph's nested-field syntax — instagram_business_account{id,username}.
        // Every builder/String overload treats those braces as a URI template variable and tries to
        // expand them, which failed the whole call with "Not enough variable values available to
        // expand 'id,username'". Percent-encoding the value and skipping the template step is what
        // lets the braces reach Graph intact.
        URI uri = URI.create("https://graph.facebook.com/v25.0/me/accounts?fields="
                + URLEncoder.encode(META_PAGE_FIELDS, StandardCharsets.UTF_8));
        try {
            String raw = restClient.get()
                .uri(uri)
                .header("Authorization", "Bearer " + userAccessToken)
                .retrieve()
                .body(String.class);

            MetaUserInfoDTO pages = objectMapper.readValue(raw, MetaUserInfoDTO.class);

            // Only logged when the list came back empty. A populated response carries a Page access
            // token per Page and must never reach the logs; an empty one carries nothing secret and
            // is the only place Graph explains itself (paging cursors, a summary, an inline warning).
            if (pages == null || pages.data() == null || pages.data().length == 0) {
                log.warn("Meta /me/accounts returned no Pages. Raw response: {}", raw);
                MetaUserInfoDTO recovered = recoverPagesFromGrantedIds(userAccessToken);
                if (recovered != null) {
                    return withResolvedInstagramAccounts(recovered, userAccessToken);
                }
            }
            return withResolvedInstagramAccounts(pages, userAccessToken);
        } catch (JacksonException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "Facebook returned a Page list that could not be read.", e);
        } catch (RestClientResponseException e) {
            // Graph rejects the token itself here — expired (user tokens last ~60 days), revoked
            // in Facebook's app settings, or invalidated by a password change. Left unhandled this
            // escapes as a bare 500, which tells the user nothing; the fix is always to reconnect.
            log.warn("Meta rejected /me/accounts: {}", e.getResponseBodyAsString());
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Facebook rejected the stored connection for this business — the access token has "
                    + "most likely expired or been revoked. Click Reconnect Facebook in your Brand "
                    + "Profile and accept every permission the dialog asks for. (Facebook said: "
                    + e.getResponseBodyAsString() + ")", e);
        }
    }

    /** The Pages named in the token's own grant, fetched one node at a time. Null when that
     * recovers nothing, so the caller can fall through to its normal "no Pages" diagnostic.
     *
     * /me/accounts can come back empty for a token that debug_token simultaneously reports as
     * carrying pages_show_list over specific Page ids — the edge is built from the user's Page
     * roles, so a Page reachable only through a Business Portfolio assignment is absent from it
     * while still being perfectly readable, and postable, as a node. Asking for the ids Meta itself
     * says the token covers is therefore both the recovery and the diagnosis: either the Pages
     * resolve and the connect flow proceeds, or Graph states a reason, which is logged verbatim.
     *
     * debug_token is called with the user token on both sides rather than an app token: Meta
     * accepts a developer's own token there, and it keeps this usable from the token alone. */
    private MetaUserInfoDTO recoverPagesFromGrantedIds(String userAccessToken) {
        String[] pageIds;
        try {
            MetaTokenDetails details = restClient.get()
                .uri(uriBuilder -> uriBuilder
                    .scheme("https")
                    .host("graph.facebook.com")
                    .path("/debug_token")
                    .queryParam("input_token", userAccessToken)
                    .queryParam("access_token", userAccessToken)
                    .build())
                .retrieve()
                .body(MetaTokenDetails.class);

            if (details == null || details.data() == null || details.data().granularScopes() == null) {
                return null;
            }
            pageIds = Arrays.stream(details.data().granularScopes())
                    .filter(g -> "pages_show_list".equals(g.scope()))
                    .map(MetaGranularScopes::targetIds)
                    .filter(Objects::nonNull)
                    .flatMap(Arrays::stream)
                    .distinct()
                    .toArray(String[]::new);
        } catch (Exception e) {
            log.warn("Could not read the granted Page ids to recover an empty /me/accounts", e);
            return null;
        }

        if (pageIds.length == 0) {
            return null;
        }
        log.info("/me/accounts was empty but the token grants pages_show_list over {} — reading each Page directly",
                Arrays.toString(pageIds));

        List<MetaDataUserInfo> recovered = new ArrayList<>();
        for (String pageId : pageIds) {
            URI uri = URI.create("https://graph.facebook.com/v25.0/" + pageId + "?fields="
                    + URLEncoder.encode(META_PAGE_FIELDS, StandardCharsets.UTF_8));
            try {
                MetaDataUserInfo page = restClient.get()
                    .uri(uri)
                    .header("Authorization", "Bearer " + userAccessToken)
                    .retrieve()
                    .body(MetaDataUserInfo.class);

                if (page != null && page.pageId() != null) {
                    recovered.add(page);
                }
            } catch (RestClientResponseException e) {
                // The whole point of this path — Graph's refusal names the cause that the empty
                // edge withheld, so it is logged in full rather than summarised away.
                log.warn("Granted Page {} could not be read directly: {}", pageId, e.getResponseBodyAsString());
            } catch (Exception e) {
                log.warn("Granted Page {} could not be read directly: {}", pageId, e.toString());
            }
        }

        if (recovered.isEmpty()) {
            return null;
        }
        log.info("Recovered {} Page(s) that /me/accounts omitted", recovered.size());
        return new MetaUserInfoDTO(recovered.toArray(MetaDataUserInfo[]::new), null);
    }

    /** Fills in the linked Instagram account for any Page the /me/accounts edge left blank.
     *
     * The edge is asked for instagram_business_account by field expansion, but Graph drops that
     * key from the edge response in cases where asking the Page node for the very same field
     * answers it — so a Page that genuinely has an Instagram account linked still comes back
     * looking unlinked, which is what put a permanent "No Instagram" badge next to it. Querying
     * the Page node is the flow Meta's own docs describe, so it is the authoritative answer here
     * and the edge is treated as a fast path.
     *
     * Only Pages that came back blank are re-queried, so a fully-populated edge response costs
     * nothing extra. A failure on any single Page leaves it null rather than failing the whole
     * Page list — one unreadable Page must not cost the user the others. */
    private MetaUserInfoDTO withResolvedInstagramAccounts(MetaUserInfoDTO pages, String userAccessToken) {
        if (pages == null || pages.data() == null || pages.data().length == 0) {
            return pages;
        }

        MetaDataUserInfo[] resolved = Arrays.stream(pages.data())
                .map(page -> page.instagramBusinessAccount() != null
                        ? page
                        : new MetaDataUserInfo(
                                page.pageAccessToken(),
                                page.category(),
                                page.categoryList(),
                                page.pageName(),
                                page.pageId(),
                                page.tasks(),
                                fetchInstagramAccountForPage(page, userAccessToken)))
                .toArray(MetaDataUserInfo[]::new);

        // Deliberately logs only the id/name/linked-ness — the Page access token is in this same
        // object and must never reach the logs.
        for (MetaDataUserInfo page : resolved) {
            log.info("Meta Page {} ({}) -> Instagram account {}", page.pageId(), page.pageName(),
                    page.instagramBusinessAccount() == null
                            ? "none"
                            : page.instagramBusinessAccount().igUserId()
                              + " (@" + page.instagramBusinessAccount().username() + ")");
        }

        return new MetaUserInfoDTO(resolved, pages.paging());
    }

    /** The Instagram account linked to one Page, or null if there genuinely isn't one.
     *
     * Tries the user token before the Page token because Meta documents instagram_business_account
     * as requiring "a User access token from someone able to perform appropriate tasks on the
     * Page" — asking with a Page token can come back empty for a Page that is in fact linked. The
     * Page token is still worth a second attempt, since it is the stronger credential for the
     * Page's own fields and answers connected_instagram_account where the user token may not. */
    private MetaInstagramAccount fetchInstagramAccountForPage(MetaDataUserInfo page, String userAccessToken) {
        List<String> tokens = page.pageAccessToken() == null || page.pageAccessToken().equals(userAccessToken)
                ? List.of(userAccessToken)
                : List.of(userAccessToken, page.pageAccessToken());

        for (int i = 0; i < tokens.size(); i++) {
            MetaInstagramAccount account = readInstagramLinkage(page.pageId(), tokens.get(i),
                    i == 0 ? "user token" : "page token");
            if (account != null) {
                return account;
            }
        }
        return null;
    }

    private MetaInstagramAccount readInstagramLinkage(Long pageId, String token, String tokenKind) {
        URI uri = URI.create("https://graph.facebook.com/v25.0/" + pageId + "?fields="
                + URLEncoder.encode("instagram_business_account{id,username},connected_instagram_account{id,username}",
                        StandardCharsets.UTF_8));
        try {
            // Read as text first and log it: this response carries no access token, so it is safe
            // to log in full, and "which of the two fields did Meta actually populate" is the one
            // question that cannot be answered from the parsed result when both come back null.
            String raw = restClient.get()
                .uri(uri)
                .header("Authorization", "Bearer " + token)
                .retrieve()
                .body(String.class);
            log.info("Instagram linkage for Page {} via {}: {}", pageId, tokenKind, raw);

            MetaPageInstagramRespDTO body = objectMapper.readValue(raw, MetaPageInstagramRespDTO.class);
            return body.instagramBusinessAccount() != null
                    ? body.instagramBusinessAccount()
                    : body.connectedInstagramAccount();
        } catch (Exception e) {
            log.warn("Could not read the Instagram account for Page {} via {}: {}", pageId, tokenKind, e.toString());
            return null;
        }
    }

    /** Why does no Page have an Instagram account, when the user believes they linked one?
     *
     * Two very different causes look identical in the Page list — the Instagram permissions were
     * never granted on this token (Graph then omits the field rather than erroring), or they were
     * granted but the account isn't a professional one linked to the Page. Only the first is
     * visible from here, so check it and let the message say which of the two to go and fix. */
    private String explainNoInstagram(String accessToken) {
        List<String> missing = new ArrayList<>();
        try {
            MetaPermissionsRespDTO permissions = restClient.get()
                .uri("https://graph.facebook.com/v25.0/me/permissions")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .body(MetaPermissionsRespDTO.class);

            if (permissions != null && permissions.data() != null) {
                List<String> granted = Arrays.stream(permissions.data())
                        .filter(p -> "granted".equalsIgnoreCase(p.status()))
                        .map(MetaPermissionsRespDTO.MetaPermission::permission)
                        .toList();

                for (String required : List.of("instagram_basic", "instagram_content_publish")) {
                    if (!granted.contains(required)) {
                        missing.add(required);
                    }
                }
            }
        } catch (Exception e) {
            log.warn("Could not read Meta permissions while diagnosing a missing Instagram account", e);
        }

        if (!missing.isEmpty()) {
            return "No Instagram account could be read because this Facebook connection is missing "
                    + String.join(" and ", missing)
                    + ". Click Reconnect Facebook and accept every permission the dialog asks for — "
                    + "including the Instagram step.";
        }

        // The permissions are fine, so Graph is reporting the Page as genuinely unlinked. Two
        // things produce that and neither is visible from here, so name both rather than asserting
        // the one that happens to be more common — picking the Instagram account in the Facebook
        // consent dialog is a third thing again, and does not link it to the Page.
        return "The Instagram permissions are granted, but Facebook still reports no Instagram "
                + "account on this Page. Two things to check, in Meta Business Suite: the Instagram "
                + "account must be a professional one (Settings > Account type — a personal account "
                + "cannot be published to through the API), and it must be linked to this specific "
                + "Page (Settings > Linked accounts). Selecting the account in the Facebook consent "
                + "dialog is not the same as linking it. Then click Refresh Pages.";
    }

    /** Why did /me/accounts come back empty? Almost always one of two things: the consent dialog
     * granted fewer permissions than were asked for, or it granted them while the user picked no
     * Page. /me/permissions distinguishes the two, so the message can name the actual next step
     * instead of leaving the user staring at an empty Page list. */
    private String explainNoPages(CrossPlatformOAuth oauth) {
        String accessToken = oauth.getAccessToken();

        // Which Pages was this token actually granted over? /me/permissions only answers whether a
        // permission was granted at all, which is why a token that carries pages_show_list over an
        // empty asset selection is indistinguishable from a healthy one there — the two look the
        // same right up until /me/accounts comes back empty. debug_token's granular_scopes is the
        // only view that separates them: it lists the Page ids each permission actually covers.
        String assetSelection = describeGrantedAssets(oauth);

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

                for (String required : META_SCOPES) {
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
                    + ". Click Reconnect Facebook and accept every permission the dialog asks for."
                    + assetSelection;
        }

        return connectedAs + "Facebook granted the page permissions but returned no Pages. In the consent dialog "
                + "you must also choose which Pages the app may use — click Reconnect Facebook and, on "
                + "the 'What Pages do you want to use with this app?' step, tick your Page (or 'Opt in to "
                + "all current and future Pages'). Also confirm the Page is a real Facebook Page rather than "
                + "a personal profile with Instagram attached, that your account has full control of it, "
                + "and that it has a role on the Meta app while the app is in Development mode."
                + assetSelection;
    }

    /** The Page ids this token was granted over, phrased for the end of a "no Pages" message.
     *
     * Empty string when it can't be read — this is an aid to an error message that already stands
     * on its own, so a failure here must never replace the guidance the user came for. */
    private String describeGrantedAssets(CrossPlatformOAuth oauth) {
        if (oauth.getClientId() == null || oauth.getClientSecret() == null) {
            return "";
        }
        try {
            MetaTokenDetails details = restClient.get()
                .uri(uriBuilder -> uriBuilder
                    .scheme("https")
                    .host("graph.facebook.com")
                    .path("/debug_token")
                    .queryParam("input_token", oauth.getAccessToken())
                    .queryParam("access_token", oauth.getClientId() + "|" + oauth.getClientSecret())
                    .build())
                .retrieve()
                .body(MetaTokenDetails.class);

            if (details == null || details.data() == null) {
                return "";
            }
            MetaDataTokenDetails data = details.data();

            log.info("Meta token debug: type={} valid={} userId={} expiresAt={} dataAccessExpiresAt={} scopes={}",
                    data.type(), data.isValid(), data.userId(), data.expiresAt(), data.dataAccessExpiresAt(),
                    data.scope() == null ? "[]" : Arrays.toString(data.scope()));

            String pageTargets = null;
            if (data.granularScopes() != null) {
                for (MetaGranularScopes granular : data.granularScopes()) {
                    // "no target_ids" is NOT "every asset" — for an asset-scoped permission it means
                    // the grant named no asset at all. Labelling it "all assets" reads as the
                    // healthiest possible state when it is in fact the emptiest, so it is spelled
                    // out as what it literally is and left uninterpreted.
                    log.info("Meta granular scope: {} -> {}", granular.scope(),
                            granular.targetIds() == null
                                    ? "no target_ids on the grant"
                                    : Arrays.toString(granular.targetIds()));
                    if ("pages_show_list".equals(granular.scope())) {
                        pageTargets = granular.targetIds() == null
                                ? null
                                : Arrays.toString(granular.targetIds());
                    }
                }
            }

            // "Granted over specific Pages, yet /me/accounts is empty" and "granted over nothing"
            // are opposite problems with opposite fixes, so say which one this token is.
            if (pageTargets == null) {
                return " (Diagnostic: this token carries no Page selection at all — pages_show_list "
                        + "was granted without any Page attached, so the Page picker step was skipped "
                        + "or no Page was ticked.)";
            }
            return " (Diagnostic: this token's pages_show_list covers " + pageTargets + ".)";
        } catch (Exception e) {
            log.warn("Could not debug the Meta token while diagnosing an empty Page list", e);
            return "";
        }
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

        MetaUserInfoDTO metaUserInfo = fetchMetaPages(crossPlatformOAuth.getAccessToken());

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
                    .uri(url, pageId)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .body(String.class));
        }
        return postIds;
    }

}
