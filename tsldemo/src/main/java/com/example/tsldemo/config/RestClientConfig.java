package com.example.tsldemo.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
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
                    System.out.println("HEADERS: " + request.getHeaders());
                    System.out.println("BODY: " + new String(body));

                    return execution.execute(request, body);
                })
                .build();
    }
}