package com.example.tsldemo.SessionAPI;

import org.springframework.data.jpa.repository.JpaRepository;

import com.example.tsldemo.Session;

public interface SessionRepository extends JpaRepository<Session, String>{

}
