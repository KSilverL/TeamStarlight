package com.example.tsldemo.SessionAPI;

import org.springframework.data.jpa.repository.JpaRepository;

import com.example.tsldemo.Message;

public interface MessageRepository extends JpaRepository<Message, Integer>{

}
