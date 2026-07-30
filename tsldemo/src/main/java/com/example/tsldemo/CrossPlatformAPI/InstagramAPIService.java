package com.example.tsldemo.CrossPlatformAPI;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.AgentAPI.AgentService;
import com.example.tsldemo.ApiDTOS.InstagramResponse;
import com.example.tsldemo.ApiDTOS.InstagramStatusResponse;
import com.example.tsldemo.CrossPlatformAPI.CrossPlatformService.InstagramTarget;

/** Publishes a rendered video to Instagram as a Reel.
 *
 * Reached through the Facebook Page the Instagram account is linked to (graph.facebook.com with
 * a Page access token), not through Instagram Login (graph.instagram.com with its own token).
 * That is what makes this multi-tenant: the credential comes from the calling business's own Meta
 * connection, resolved per request, so there is no shared account and nothing to configure
 * per deployment.
 *
 * Publishing is a three-step handshake, not one upload. Graph will not accept video bytes: it
 * fetches the file itself, so the MP4 is staged in blob storage and handed over as a short-lived
 * SAS URL. Then a media container is created, Instagram transcodes asynchronously, and only once
 * it reports FINISHED can the container be published. */
@Service
public class InstagramAPIService {

    private static final Logger log = LoggerFactory.getLogger(InstagramAPIService.class);

    private static final String GRAPH_HOST = "graph.facebook.com";
    private static final String GRAPH_VERSION = "/v25.0";

    /** How long to wait for Instagram to transcode before giving up. Transcoding is asynchronous
     * and routinely takes tens of seconds; a long clip can take minutes. Because the wait now runs
     * on a background thread rather than the request thread, this ceiling is bounded by how long a
     * publish can plausibly be worth tracking rather than by any HTTP timeout — but it must stay
     * comfortably inside the SAS URL lifetime in VideoStorageService, or Instagram loses access to
     * the file it is still fetching. */
    private static final int MAX_STATUS_ATTEMPTS = 40;
    private static final long STATUS_POLL_INTERVAL_MILLIS = 15_000L;

    private final RestClient restClient;
    private final VideoStorageService videoStorageService;
    private final AgentService agentService;
    private final CrossPlatformService crossPlatformService;
    private final InstagramPublishJobStore jobStore;
    private final Executor publishExecutor;

    public InstagramAPIService(RestClient restClient,
                               VideoStorageService videoStorageService,
                               AgentService agentService,
                               CrossPlatformService crossPlatformService,
                               InstagramPublishJobStore jobStore,
                               @Qualifier("instagramPublishExecutor") Executor publishExecutor) {
        this.restClient = restClient;
        this.videoStorageService = videoStorageService;
        this.agentService = agentService;
        this.crossPlatformService = crossPlatformService;
        this.jobStore = jobStore;
        this.publishExecutor = publishExecutor;
    }

    /** Starts publishing the rendered video for {@code videoJobId} as a Reel on the Instagram
     * account behind each of the given Pages, and returns a job to poll for the outcome.
     *
     * Credentials are resolved synchronously, before returning, so the common mistakes — Facebook
     * not connected, no Instagram account linked to the Page — are still reported in the response
     * to this call rather than only showing up in a later poll. Only the genuinely slow part, the
     * transcode wait, goes to the background.
     *
     * @param businessId taken from the caller's JWT — never from the request body
     * @param pageIds    the Facebook Pages selected in the Brand Profile
     */
    public InstagramPublishJob startPostVideo(long businessId, List<Long> pageIds,
                                             String videoJobId, String caption) {
        List<InstagramTarget> targets = crossPlatformService.resolveInstagramTargets(businessId, pageIds);

        InstagramPublishJob job = jobStore.create(businessId);
        publishExecutor.execute(() -> runPublish(job, targets, videoJobId, caption));
        return job;
    }

    private void runPublish(InstagramPublishJob job, List<InstagramTarget> targets,
                            String videoJobId, String caption) {
        try {
            job.setStage("Fetching the rendered video");
            byte[] videoBytes = agentService.downloadVideo(videoJobId);
            if (videoBytes == null || videoBytes.length == 0) {
                job.fail("The rendered video for job " + videoJobId + " could not be downloaded, so "
                        + "there was nothing to publish. Re-render the video and try again.");
                return;
            }

            // One staged upload serves every target — the SAS URL is read-only and Graph only needs
            // to be able to fetch it, so re-uploading per account would buy nothing.
            job.setStage("Staging the video for Instagram");
            String sasVideoUrl = videoStorageService.uploadAndGetSasUrl(videoBytes, videoJobId, videoBytes.length);

            List<String> mediaIds = new ArrayList<>();
            for (InstagramTarget target : targets) {
                job.setStage("Publishing to @" + target.username());
                mediaIds.add(publishReel(job, target, sasVideoUrl, caption));
            }
            job.succeed(mediaIds);
            log.info("Instagram publish job {} published media {}", job.getId(), mediaIds);

        } catch (ResponseStatusException e) {
            // Reasons here are written for the user and name the fix; keep them.
            job.fail(e.getReason() == null ? e.getMessage() : e.getReason());
            log.warn("Instagram publish job {} failed: {}", job.getId(), e.getReason());
        } catch (Exception e) {
            // Nothing is holding a request open any more, so an escaping exception would otherwise
            // just leave the job PENDING for ever and the UI spinning.
            job.fail("Publishing to Instagram failed unexpectedly: " + e.getMessage());
            log.error("Instagram publish job {} failed unexpectedly", job.getId(), e);
        }
    }

    private String publishReel(InstagramPublishJob job, InstagramTarget target,
                              String videoUrl, String caption) {
        String containerId = graphCall("create the media container for @" + target.username(), () ->
                restClient.post()
                        .uri(uriBuilder -> uriBuilder
                                .scheme("https")
                                .host(GRAPH_HOST)
                                .path(GRAPH_VERSION + "/" + target.igUserId() + "/media")
                                .queryParam("media_type", "REELS")
                                .queryParam("video_url", videoUrl)
                                .queryParam("caption", caption == null ? "" : caption)
                                .queryParam("access_token", target.pageAccessToken())
                                .build())
                        .retrieve()
                        .body(InstagramResponse.class));

        waitUntilReady(job, containerId, target);

        return graphCall("publish the media container for @" + target.username(), () ->
                restClient.post()
                        .uri(uriBuilder -> uriBuilder
                                .scheme("https")
                                .host(GRAPH_HOST)
                                .path(GRAPH_VERSION + "/" + target.igUserId() + "/media_publish")
                                .queryParam("creation_id", containerId)
                                .queryParam("access_token", target.pageAccessToken())
                                .build())
                        .retrieve()
                        .body(InstagramResponse.class));
    }

    private void waitUntilReady(InstagramPublishJob job, String containerId, InstagramTarget target) {
        for (int attempt = 1; attempt <= MAX_STATUS_ATTEMPTS; attempt++) {
            job.setStage("Instagram is processing the video for @" + target.username()
                    + " (" + attempt + "/" + MAX_STATUS_ATTEMPTS + ")");
            InstagramStatusResponse status = restClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .scheme("https")
                            .host(GRAPH_HOST)
                            .path(GRAPH_VERSION + "/" + containerId)
                            .queryParam("fields", "status_code,status")
                            .queryParam("access_token", target.pageAccessToken())
                            .build())
                    .retrieve()
                    .body(InstagramStatusResponse.class);

            String code = status == null ? null : status.status_code();
            log.info("Instagram container {} status check {}/{}: {}",
                    containerId, attempt, MAX_STATUS_ATTEMPTS, code);

            if ("FINISHED".equalsIgnoreCase(code)) {
                return;
            }
            if ("ERROR".equalsIgnoreCase(code) || "EXPIRED".equalsIgnoreCase(code)) {
                // `status` carries Instagram's own explanation where status_code is just a label —
                // usually an unsupported aspect ratio, codec, or duration.
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                        "Instagram could not process the video: "
                        + (status.status() == null ? code : status.status())
                        + ". Reels must be MP4/MOV, 3–90 seconds, and roughly 9:16.");
            }

            try {
                Thread.sleep(STATUS_POLL_INTERVAL_MILLIS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,
                        "Interrupted while waiting for Instagram to process the video.", e);
            }
        }

        // The container may still finish and remain publishable for ~24h, so this is explicitly
        // not "the post failed" — saying so would invite a retry that double-posts.
        throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT,
                "Instagram is still processing the video after "
                + (MAX_STATUS_ATTEMPTS * STATUS_POLL_INTERVAL_MILLIS / 1000) + "s. It may still publish "
                + "on its own — check the account before retrying, or a duplicate may be posted.");
    }

    /** Runs a Graph call that is expected to return an id.
     *
     * Graph signals failure in two ways that both used to surface as a bare 500: a non-2xx with a
     * JSON body naming the reason, and — for some permission and rate-limit cases — a 200 whose
     * body carries no id at all, which made {@code response.id()} throw NullPointerException. Both
     * become a message that names the actual problem. */
    private String graphCall(String what, java.util.function.Supplier<InstagramResponse> call) {
        InstagramResponse response;
        try {
            response = call.get();
        } catch (RestClientResponseException e) {
            log.warn("Instagram rejected an attempt to {}: {}", what, e.getResponseBodyAsString());
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "Instagram refused to " + what + ": " + e.getResponseBodyAsString(), e);
        }

        if (response == null || response.id() == null || response.id().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "Instagram accepted the request to " + what + " but returned no media id. This is "
                    + "usually a missing instagram_content_publish permission or the 25-posts-per-day "
                    + "publishing limit — reconnect Facebook, accepting every permission, and check "
                    + "how many posts the account has published today.");
        }
        return response.id();
    }
}
