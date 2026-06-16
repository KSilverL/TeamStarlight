package com.example.tsldemo.SignInAPI;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import com.example.tsldemo.Business;

@RestController
public class BusinessController {
	private BusinessService service;
	
	public BusinessController(BusinessService service) {
		this.service = service;
	}
	
	@PostMapping("/signIn")
	public String createAccount(@RequestBody Business b) {
		service.addBusinessToDB(b);
		return "Account created: " + b.toString();
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


