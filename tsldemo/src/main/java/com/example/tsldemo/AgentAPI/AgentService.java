package com.example.tsldemo.AgentAPI;

import java.net.URI;
import java.util.HashMap;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.util.stream.Stream;

import java.net.http.HttpResponse;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;

import com.example.tsldemo.ApiDTOS.*;

import io.netty.util.internal.shaded.org.jctools.queues.MessagePassingQueue.Consumer;
import tools.jackson.databind.ObjectMapper;


@Service
public class AgentService {
	private final RestClient restClient;
	private final ObjectMapper mapper = new ObjectMapper();

	private final HttpClient http = HttpClient.newHttpClient();
	
	@Value("${llm.service.base-url:http://localhost:8080}")
	private String llmServiceBaseUrl;
	
	public AgentService(RestClient restClient) {
        this.restClient = restClient;
    }
	
	private <T> T post(String path, Object request, Class<T> responseType) {
	    return restClient.post()
	            .uri(llmServiceBaseUrl + path)
	            .contentType(MediaType.APPLICATION_JSON)
	            .body(request)
	            .retrieve()
	            .body(responseType);
	}
	
	private <T> T get(String path, Class<T> responseType) {
        return restClient.get()
                .uri(llmServiceBaseUrl + path)
                .retrieve()
                .body(responseType);
    }

	
	public GenerateTextResponse generateText(GenerateTextRequest request) {
        return post("/generate-text", request, GenerateTextResponse.class);
    }

    public GenerateHtmlResponse generateHtmlCard(GenerateHtmlRequest request) {
        return post("/generate", request, GenerateHtmlResponse.class);
    }

    public RenderVideoResponse renderVideo(String taskId, String platform) {
        return post(
            "/tasks/" + taskId + "/render-video",
            new RenderVideoRequest(platform),
            RenderVideoResponse.class
        );
    }

    public VideoJobResponse getVideoJob(String jobId) {
        return get("/video-jobs/" + jobId, VideoJobResponse.class);
    }

    public byte[] downloadVideo(String jobId) {
        return restClient.get()
                .uri(llmServiceBaseUrl + "/video-jobs/" + jobId + "/download")
                .retrieve()
                .body(byte[].class);
    }
	
	public TaskSnapshot getTaskSnapshot(String taskId) {
	    return restClient.get()
	            .uri(llmServiceBaseUrl + "/tasks/" + taskId)
	            .retrieve()
	            .body(TaskSnapshot.class);
	}
	
	public TaskSnapshot startTask(CreativeBrief brief) {
		return restClient.post()
                .uri(llmServiceBaseUrl + "/tasks")
                .contentType(MediaType.APPLICATION_JSON)
                .body(brief)
                .retrieve()
                .body(TaskSnapshot.class);
	}
	
	public TaskSnapshot reviewTask(String taskId, ReviewRequest request) {
	    return post(
	            "/tasks/" + taskId + "/review",
	            request,
	            TaskSnapshot.class
	    );
	}
	
	public ConfirmLearningResponse agentConfirmLearning(Boolean learn, String taskId) {
	    return post(
	            "/tasks/" + taskId + "/confirm-learning",
	            new ConfirmLearningRequest(learn),
	            ConfirmLearningResponse.class
	    );
	}

	public RaiseHandResponse agentRaiseHand(String taskId, String tableId) {
	    return post(
	            "/tasks/" + taskId + "/raise-hand",
	            new RaiseHandRequest(tableId),
	            RaiseHandResponse.class
	    );
	}

	public SayResponse agentSay(String taskId, SayRequest request) {
	    return post(
	            "/tasks/" + taskId + "/say",
	            request,
	            SayResponse.class
	    );
	}

	public RoundControlResponse agentRoundControl(String taskId, RoundControlRequest request) {
	    return post(
	            "/tasks/" + taskId + "/round-control",
	            request,
	            RoundControlResponse.class
	    );
	}
	
	
	public Thread consumeEvents(String taskId, Consumer<Map<String, Object>> onEvent) {
	    Thread t = new Thread(() -> {
	        try {
	            HttpRequest request = HttpRequest.newBuilder()
	                    .uri(URI.create(llmServiceBaseUrl + "/tasks/" + taskId + "/events"))
	                    .GET()
	                    .build();

	            HttpResponse<Stream<String>> response =
	                    http.send(request, HttpResponse.BodyHandlers.ofLines());

	            response.body()
	                    .filter(line -> line.startsWith("data: "))
	                    .forEach(line -> {
	                        try {
	                            Map<String, Object> ev = mapper.readValue(line.substring(6), Map.class);
	                            onEvent.accept(ev);
	                        } catch (Exception e) {
	                            e.printStackTrace();
	                        }
	                    });
	        } catch (Exception e) {
	            e.printStackTrace(); // now only fires for genuine connection errors
	        }
	    });
	    
	    t.setDaemon(true);
	    t.start();
	    
	    return t;
	}
	
	
}
