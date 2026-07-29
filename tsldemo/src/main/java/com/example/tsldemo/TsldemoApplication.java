package com.example.tsldemo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
@EnableAsync
public class TsldemoApplication {

    public static void main(String[] args) {
        SpringApplication.run(TsldemoApplication.class, args);
    }

}