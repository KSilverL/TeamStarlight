package com.example.tsldemo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class BusinessController {
	private BusinessService service;
	
	public BusinessController(BusinessService service) {
		this.service = service;
	}
	
	@PostMapping("/business")
	public String createAccount(@RequestBody Business b) {
		service.addBusinessToDB(b);
		return "Account created: " + b.toString();
	}
	
	@GetMapping("/business")
	public String viewBusinesses() {
		return service.getAllBusinesses().toString();
		
	}
	
}


/***
 * Sample curl post request to add business users
 curl -X POST http://localhost:8080/business \
  -H "Content-Type: application/json" \
  -d '{
    "id": 1,
    "name": "Acme Corp",
    "username": "acme_user",
    "password": "secret123",
    "inputData": "Sample input data"
  }'
 ***/
