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
	
	/** Returns the matching Business, or null if credentials are invalid. */
	public Business checkCredentials(String email, String password) {
		Business b = businessRepo.findByEmail(email);
		if (b != null && b.getPassword().equals(password)) {
			return b;
		}
		return null;
	}
}
