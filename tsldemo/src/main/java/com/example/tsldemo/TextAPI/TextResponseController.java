package com.example.tsldemo.TextAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;


@RestController
public class TextResponseController {
	
	@PostMapping("/generate-text")
	public String extractUserPrompt(@RequestBody String prompt) {
		ObjectMapper objMap = new ObjectMapper();
		Map<String, String> promptJSON = objMap.readValue(prompt, new TypeReference<Map<String,String>>(){});
		Map<String, String> mockResponse = new HashMap();
		
		mockResponse.put("text", "Message from Agent :)");
		mockResponse.put("platform", promptJSON.get("platform"));
		
		return objMap.writeValueAsString(mockResponse);
		
	}
	
	
}
