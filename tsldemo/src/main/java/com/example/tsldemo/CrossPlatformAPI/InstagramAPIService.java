package com.example.tsldemo.CrossPlatformAPI;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.ApiDTOS.InstagramResponse;
import com.example.tsldemo.ApiDTOS.InstagramStatusResponse;
import com.example.tsldemo.AgentAPI.AgentService;

@Service
public class InstagramAPIService {
//
//    private final String graphUrl = "https://graph.instagram.com/v23.0/";

    @Value("${instagram.account.id}")
    private String accountId;

    @Value("${instagram.account.token}")
    private String accessToken;

    private final RestClient restClient;
    private final VideoStorageService videoStorageService;
    private final AgentService agentService;

    public InstagramAPIService(RestClient restClient, VideoStorageService videoStorageService, AgentService agentService) {
        this.restClient = restClient;
        this.videoStorageService = videoStorageService;
        this.agentService = agentService;
    }

    public String postVideo(String videoJobId, String caption) throws Exception {
    	byte[] videoBytes = agentService.downloadVideo(videoJobId);
    	
        String sasVideoUrl = videoStorageService.uploadAndGetSasUrl(videoBytes, videoJobId, videoBytes.length);

        InstagramResponse container = restClient.post()
                .uri(uriBuilder -> uriBuilder
                        .scheme("https")
                        .host("graph.instagram.com")
                        .path("/v23.0/" + accountId + "/media")
                        .queryParam("media_type", "REELS")
                        .queryParam("video_url", sasVideoUrl)
                        .queryParam("caption", caption)
                        .queryParam("access_token", accessToken)
                        .build())
                .retrieve()
                .body(InstagramResponse.class);

        waitUntilReady(container.id());

        InstagramResponse publishResponse = restClient.post()
                .uri(uriBuilder -> uriBuilder
                        .scheme("https")
                        .host("graph.instagram.com")
                        .path("/v23.0/" + accountId + "/media_publish")
                        .queryParam("creation_id", container.id())
                        .queryParam("access_token", accessToken)
                        .build())
                .retrieve()
                .body(InstagramResponse.class);

        return publishResponse.id();
    }

    private void waitUntilReady(String containerId) {
        int maxAttempts = 10; 
        int attempt = 0;
        int delayMillis = 30000;

        while (true) {
            attempt++;

            InstagramStatusResponse status = restClient.get()
                    .uri(uriBuilder -> uriBuilder
                            .scheme("https")
                            .host("graph.instagram.com")
                            .path("/v23.0/" + containerId)
                            .queryParam("fields", "status_code")
                            .queryParam("access_token", accessToken)
                            .build())
                    .retrieve()
                    .body(InstagramStatusResponse.class);

            System.out.println("Attempt " + attempt + " - status: " + status.status_code());

            if ("FINISHED".equalsIgnoreCase(status.status_code())) {
                break;
            }
            if ("ERROR".equalsIgnoreCase(status.status_code())) {
                throw new RuntimeException("Instagram failed to process the media, container id: " + containerId);
            }
            if (attempt >= maxAttempts) {
                throw new RuntimeException("Timed out waiting for Instagram to process media, container id: " + containerId);
            }

            try {
                Thread.sleep(delayMillis);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new RuntimeException("Interrupted while waiting for Instagram media processing", e);
            }
        }
    }
}