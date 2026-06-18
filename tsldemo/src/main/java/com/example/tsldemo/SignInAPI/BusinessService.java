package com.example.tsldemo.SignInAPI;

import java.util.List;

import org.springframework.stereotype.Service;

import com.example.tsldemo.Business;

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
	
	public void deleteBusiness(int id) {
		businessRepo.deleteById(id);
	}
	
}
