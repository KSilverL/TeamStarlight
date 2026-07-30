package com.example.tsldemo.CrossPlatformAPI;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.example.tsldemo.CrossPlatformOAuth;
import com.example.tsldemo.ENUMS.PlatformEnum;

import jakarta.transaction.Transactional;

public interface CrossPlatformRepository extends JpaRepository<CrossPlatformOAuth, Long>{
	
    CrossPlatformOAuth findByStateAndPlatform(String state, PlatformEnum platform);

    CrossPlatformOAuth findByBusinessIdAndPlatform(Long businessId, PlatformEnum platform);

    // Overload for the LinkedIn flow, which carries the business id as the primitive int it
    // extracts from the JWT. The businessId column is a Long, but Spring Data binds the int
    // parameter to it fine — this just spares every LinkedIn call site an explicit boxing.
    CrossPlatformOAuth findByBusinessIdAndPlatform(int businessId, PlatformEnum platform);

    List<CrossPlatformOAuth> findByBusinessIdAndPlatformIn(Long businessId, List<PlatformEnum> platforms);

    @Transactional
    void deleteByBusinessIdAndPlatformIn(@Param("businessId") Long businessId, @Param("platforms") List<PlatformEnum> platforms);
}
