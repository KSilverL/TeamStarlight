package com.example.tsldemo.LoginAPI;

import org.springframework.stereotype.Service;

import com.example.tsldemo.Business;
import com.example.tsldemo.SignInAPI.BusinessRepository;

@Service
public class LoginService {
	private BusinessRepository businessRepo;
	
	public LoginService(BusinessRepository businessRepo) {
		this.businessRepo = businessRepo;
	}
	
	public boolean checkCredentials(String email, String password) {
		Business b = businessRepo.findByEmail(email);
		
		return b.getEmail().equals(email) && b.getPassword().equals(password);
		
	}
}
