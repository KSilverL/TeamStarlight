package com.example.tsldemo.LoginAPI;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

@Controller
public class LoginController {
	private LoginService loginService;
	
	public LoginController(LoginService loginService) {
		this.loginService = loginService;
	}
	
	@GetMapping("/verifyLogin")
	@ResponseBody
	public String verifyLogin(@RequestParam(name = "email") String email, @RequestParam String password) {
		if(loginService.checkCredentials(email, password)) {
			return "Access Granted";
		}
		return "Access Denied";
	}

}
