package com.example.tsldemo;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

import com.example.tsldemo.SessionAPI.SessionRepository;
import com.example.tsldemo.auth.JwtUtil;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;


@SpringBootTest
@AutoConfigureMockMvc
class SessionControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private SessionRepository sessionRepository;

    @MockitoBean
    private JwtUtil jwtUtil;


    @Test
    @Transactional
    void addMessage_shouldPersistMessage() throws Exception {

        // Create a session in the database
        Session session = new Session();
        sessionRepository.save(session);

        String json = """
        {
          "role":"user",
          "content":"Hello"
        }
        """;

        // Call POST /api/sessions/{id}/messages
        mockMvc.perform(post("/api/sessions/" + session.getId() + "/messages")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json))
                .andExpect(status().isOk());

        // Verify message was persisted
        Session updated = sessionRepository.findById(session.getId()).orElseThrow();

        assertEquals(1, updated.getMessages().size());
        assertEquals("Hello", updated.getMessages().get(0).getContent());
    }
}