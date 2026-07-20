package com.example.tsldemo.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.web.client.RestClient;

@Configuration
public class RestClientConfig {

    @Bean
    public RestClient restClient() {
        return RestClient.builder()
                .requestInterceptor((request, body, execution) -> {

                    System.out.println("=== OUTGOING REQUEST ===");
                    System.out.println("URI: " + request.getURI());
                    System.out.println("METHOD: " + request.getMethod());
                    // Copy before masking — request.getHeaders() is the live outgoing map, so
                    // redacting in place would strip the credential off the actual request.
                    HttpHeaders safeHeaders = new HttpHeaders();
                    safeHeaders.putAll(request.getHeaders());
                    if (safeHeaders.containsKey(HttpHeaders.AUTHORIZATION)) {
                        safeHeaders.set(HttpHeaders.AUTHORIZATION, "Bearer <redacted>");
                    }
                    System.out.println("HEADERS: " + safeHeaders);
                    System.out.println("BODY: " + new String(body));

                    return execution.execute(request, body);
                })
                .build();
    }
}