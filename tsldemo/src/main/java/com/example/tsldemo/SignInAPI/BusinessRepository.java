package com.example.tsldemo.SignInAPI;

import org.springframework.data.jpa.repository.JpaRepository;

import com.example.tsldemo.Business;

public interface BusinessRepository extends JpaRepository<Business, Integer>{
	Business findByEmail(String email);

	Business findById(Long id);
}
