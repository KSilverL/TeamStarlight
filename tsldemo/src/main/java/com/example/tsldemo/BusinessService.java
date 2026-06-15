package com.example.tsldemo;

import java.util.List;

import org.springframework.stereotype.Service;

@Service
public class BusinessService {
	private BusinessRepository businessRepo;
	
	public BusinessService(BusinessRepository businessRepo) {
		this.businessRepo = businessRepo;
	}
	
	public List<Business> getAllBusinesses() {
		return businessRepo.findAll();
	}
	
	public void addBusinessToDB(Business business) {
		businessRepo.save(business);
	}
	
}
