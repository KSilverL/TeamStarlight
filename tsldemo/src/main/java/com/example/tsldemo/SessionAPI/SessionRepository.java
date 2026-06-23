package com.example.tsldemo.SessionAPI;

import org.springframework.data.jpa.repository.JpaRepository;

import com.example.tsldemo.Session;
import java.util.List;

public interface SessionRepository extends JpaRepository<Session, String>{
	List<Session> findByUser_Id(int userId);
}
