package com.example.tsldemo.CrossPlatformAPI;

import org.springframework.data.jpa.repository.JpaRepository;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.ENUMS.PlatformEnum;

public interface CrossPlatformRepository extends JpaRepository<CrossPlatformOAuth, Long>{
	
    CrossPlatformOAuth findByStateAndPlatform(String state, PlatformEnum platform);

    CrossPlatformOAuth findByBusinessIdAndPlatform(String businessId, PlatformEnum platform);

}
