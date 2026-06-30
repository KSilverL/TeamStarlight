package com.example.tsldemo.AgentAPI;

import java.util.HashMap;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;


@RestController
public class AgentController {
	@Autowired
	private AgentService service;
	
	@PostMapping("/generate-text")
	public String extractAssisstantResponse(@RequestBody String prompt) {
		System.out.println(prompt);
		ObjectMapper objMap = new ObjectMapper();
		Map<String, Object> promptJSON = objMap.readValue(prompt, new TypeReference<Map<String, Object>>() {});
		
		
		Map<String, Object> response = service.getAgentTextResponse(promptJSON);
		
		System.out.println(response.get("assistant_message"));
		
		return objMap.writeValueAsString(response);
		
	}
	
}
