package com.example.tsldemo.config;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.regex.Pattern;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.ReactorClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class RestClientConfig {

    /** Uploads (a video to Graph, an image to LinkedIn) are the slow calls here: the request body
     * has to go up in full and the platform then processes it before it answers. Reactor Netty's
     * stock 10s read timeout aborts those long before a response arrives — a ~1MB video to
     * /{page_id}/videos died at exactly 10s with ReadTimeoutException. */
    private static final Duration UPLOAD_READ_TIMEOUT = Duration.ofMinutes(5);

    /** Enough of a body to identify the call; anything past this is noise in the logs. */
    private static final int MAX_LOGGED_BODY_CHARS = 2_000;

    /** Meta takes its credential as an `access_token` form field rather than a header, so header
     * redaction alone still left live page tokens in the logs. */
    private static final Pattern ACCESS_TOKEN = Pattern.compile("(access_token\"?\\s*[=:]\\s*\"?)[^\"&,\\s]+");

    @Bean
    public RestClient restClient() {
        ReactorClientHttpRequestFactory requestFactory = new ReactorClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(30));
        requestFactory.setReadTimeout(UPLOAD_READ_TIMEOUT);

        return RestClient.builder()
                .requestFactory(requestFactory)
                .requestInterceptor((request, body, execution) -> {

                    System.out.println("=== OUTGOING REQUEST ===");
                    System.out.println("URI: " + request.getURI());
                    System.out.println("METHOD: " + request.getMethod());
                    // Copy before masking — request.getHeaders() is the live outgoing map, so
                    // redacting in place would strip the credential off the actual request.
                    HttpHeaders safeHeaders = new HttpHeaders();
                    request.getHeaders().forEach(safeHeaders::addAll);
                    if (safeHeaders.containsHeader(HttpHeaders.AUTHORIZATION)) {
                        safeHeaders.set(HttpHeaders.AUTHORIZATION, "Bearer <redacted>");
                    }
                    System.out.println("HEADERS: " + safeHeaders);
                    System.out.println("BODY: " + describeBody(safeHeaders.getContentType(), body));

                    return execution.execute(request, body);
                })
                .build();
    }

    /** Renders a request body for the log without dumping credentials or megabytes of binary.
     * Multipart is summarised rather than printed: it carries raw file bytes, and Meta puts the
     * page access token in it as a plain form field. */
    private static String describeBody(MediaType contentType, byte[] body) {
        if (body == null || body.length == 0) {
            return "<empty>";
        }
        if (contentType != null && MediaType.MULTIPART_FORM_DATA.isCompatibleWith(contentType)) {
            return "<multipart/form-data, " + body.length + " bytes — not logged (raw file bytes and access tokens)>";
        }

        String text = ACCESS_TOKEN.matcher(new String(body, StandardCharsets.UTF_8)).replaceAll("$1<redacted>");
        if (text.length() > MAX_LOGGED_BODY_CHARS) {
            return text.substring(0, MAX_LOGGED_BODY_CHARS) + "… <truncated, " + body.length + " bytes total>";
        }
        return text;
    }
}
