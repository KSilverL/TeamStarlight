package com.example.tsldemo;

import java.time.Instant;

import com.example.tsldemo.ENUMS.PlatformEnum;
import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Entity
@Table(name = "cross_platform_oauth")
public class CrossPlatformOAuth {
    @Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	@JsonProperty("id")
    private Long id;
    @ManyToOne
    @JoinColumn(name = "businessId", referencedColumnName = "id", nullable = false)
    @JsonProperty("businessId")
    private Business businessId;
    @JsonProperty("urn")
    private String urn;
    @JsonProperty("clientId")
    private String clientId;
    @JsonProperty("clientSecret")
    private String clientSecret;
    @Enumerated(EnumType.STRING)
    @JsonProperty("platform")
    private PlatformEnum platform;
    @Column(columnDefinition = "TEXT")
    @JsonProperty("accessToken")
    private String accessToken;
    @JsonProperty("expiresAt")
    private Instant expiresAt;
    @JsonProperty("state")
    private String state;
    @JsonProperty("pageIdArray")
    private Long[] pageIdArray;
    @JsonProperty("pageNameArray")
    private String[] pageNameArray;

}