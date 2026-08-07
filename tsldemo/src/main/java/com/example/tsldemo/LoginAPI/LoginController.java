package com.example.tsldemo.LoginAPI;

import com.example.tsldemo.Business;
import com.example.tsldemo.auth.JwtUtil;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
public class LoginController {

    private final LoginService loginService;
    private final JwtUtil jwtUtil;

    public LoginController(LoginService loginService, JwtUtil jwtUtil) {
        this.loginService = loginService;
        this.jwtUtil = jwtUtil;
    }

    /**
     * Signing in is refused outright to anyone who already holds a session.
     *
     * The browser keeps exactly one token, so a second login silently replaces the first —
     * quietly switching which business every later request is scoped to. The caller has to log
     * out first, which is a deliberate act rather than a side effect of a form submission.
     *
     * An expired or malformed token reads as no session at all (JwtUtil.extractBusinessId
     * returns -1 for both), so it never stands between someone and a fresh login.
     */
    @PostMapping("/login")
    public ResponseEntity<?> login(
            @RequestBody Map<String, String> body,
            @RequestHeader(value = "Authorization", required = false) String authHeader) {

        if (jwtUtil.extractBusinessId(authHeader) != -1) {
            return ResponseEntity.status(409).body(Map.of("error", "Already signed in. Log out first."));
        }

        String email = body.get("email");
        String password = body.get("password");

        if (email == null || password == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "email and password are required"));
        }

        Business business = loginService.checkCredentials(email, password);
        if (business == null) {
            return ResponseEntity.status(401).body(Map.of("error", "Invalid email or password"));
        }

        String token = jwtUtil.generateToken(business.getId());
        return ResponseEntity.ok(Map.of("token", token));
    }
}
