package com.example.tsldemo.config;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/** Puts a {@link ResponseStatusException}'s reason into the response body as {@code error}.
 *
 * Spring Boot's default error body omits the reason unless {@code server.error.include-message}
 * is set, so a carefully written "link an Instagram account to this Page, then reconnect" reached
 * the browser as a bare "Bad Request" — the reason IS the payload for these, since it names the
 * step the user has to take. Individual endpoints had started catching and re-wrapping their own
 * exceptions to work around this; this handles it once, in the shape the frontend already reads
 * ({@code data.error}).
 *
 * Deliberately scoped to ResponseStatusException only. Those carry messages written for a user;
 * an arbitrary unhandled exception carries internals, and is left to Spring's default handling
 * rather than being echoed back. */
@RestControllerAdvice
public class ResponseStatusExceptionAdvice {

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, String>> handle(ResponseStatusException e) {
        String reason = e.getReason() == null || e.getReason().isBlank()
                ? e.getStatusCode().toString()
                : e.getReason();
        return ResponseEntity.status(e.getStatusCode()).body(Map.of("error", reason));
    }
}
