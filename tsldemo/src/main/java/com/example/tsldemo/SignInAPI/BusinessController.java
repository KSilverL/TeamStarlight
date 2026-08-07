package com.example.tsldemo.SignInAPI;

import java.util.List;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import com.example.tsldemo.Business;
import com.example.tsldemo.auth.JwtUtil;

@RestController
public class BusinessController {
	private BusinessService service;
	private final JwtUtil jwtUtil;

	public BusinessController(BusinessService service, JwtUtil jwtUtil) {
		this.service = service;
		this.jwtUtil = jwtUtil;
	}

	/**
	 * Refused while a session is open, for the same reason as POST /login: the browser holds
	 * one token, so creating a second account from inside the first one's session would leave
	 * the caller signed in as neither the account they had nor the one they just made.
	 */
	@PostMapping("/signIn")
	public ResponseEntity<?> createAccount(
			@RequestBody Business b,
			@RequestHeader(value = "Authorization", required = false) String authHeader) {

		if (jwtUtil.extractBusinessId(authHeader) != -1) {
			return ResponseEntity.status(409).body(Map.of("error", "Already signed in. Log out first."));
		}

		service.addBusinessToDB(b);
		return ResponseEntity.ok("Account created: " + b.toString());
	}
	
	@GetMapping("/signIn")
	public List<Business> viewBusinesses() {
		return service.getAllBusinesses();
		
	}
	
}


/***
 * Sample curl post request to add business users
 curl -X POST http://localhost:8080/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
  "businessDescription": "EcoHome Solutions - we sell sustainable bamboo home products",
  "brandTone": "warm, aspirational, educational",
  "targetPlatforms": ["instagram", "linkedin"],
  "contentTopics": "Bamboo Kitchen Collection launch",
  "contentType": "mix",
  "notes": "Emphasise sustainability and durability",
  "userPreferences": "Prefer storytelling over promotional copy"
}'
 ***/

/***
 * Sample curl post request to add business users
 curl -X POST http://localhost:8080/api/sess-6bcb840c/sessions \
  -H "Content-Type: application/json" \
  -d '{
  "content": "We're EcoHome Solutions - we sell sustainable bamboo home products targeting eco-conscious millennials aged 25–40. Our brand tone is warm, aspirational, and educational. We want to promote our new Bamboo Kitchen Collection across Instagram and LinkedIn."
}'
 ***/


