package com.example.tsldemo.auth;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import javax.crypto.SecretKey;
import java.util.Date;

@Component
public class JwtUtil {
	private final RestClient restClient;

    private static final long EXPIRY_MS = 7 * 24 * 60 * 60 * 1000L; // 7 days

    private final SecretKey key;
    

    public JwtUtil(@Value("${jwt.secret}") String secret, RestClient restClient) {
        // HMAC-SHA key requires at least 32 bytes; pad if the configured secret is short.
        byte[] bytes = secret.getBytes();
        if (bytes.length < 32) {
            byte[] padded = new byte[32];
            System.arraycopy(bytes, 0, padded, 0, bytes.length);
            bytes = padded;
        }
        this.key = Keys.hmacShaKeyFor(bytes);
        this.restClient = restClient;
    }
    

    public String generateToken(int businessId) {
        return Jwts.builder()
                .subject(String.valueOf(businessId))
                .issuedAt(new Date())
                .expiration(new Date(System.currentTimeMillis() + EXPIRY_MS))
                .signWith(key)
                .compact();
    }

    /** Returns the businessId encoded in the token, or -1 if invalid/expired. */
    public int extractBusinessId(String authHeader) {
    	if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            return -1;
        }

        String token = authHeader.substring(7);

        try {
            String subject = Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload()
                    .getSubject();

            return Integer.parseInt(subject);

        } catch (Exception e) {
            return -1;
        }
    }
    
    private <T> T post(String path, Object request, Class<T> responseType, String url) {
		return restClient.post()
	            .uri(url + path)
	            .contentType(MediaType.APPLICATION_JSON)
	            .body(request)
	            .retrieve()
	            .body(responseType);
	}
	
	private <T> T get(String path, Class<T> responseType, String url) {
        return restClient.get()
                .uri(url + path)
                .retrieve()
                .body(responseType);
    }
    

  
}
