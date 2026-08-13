package com.example.tsldemo.AgentAPI;

import org.springframework.data.jpa.repository.JpaRepository;

import com.example.tsldemo.TaskOwner;

public interface TaskOwnerRepository extends JpaRepository<TaskOwner, String> {
}
