package com.example.tsldemo;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import com.example.tsldemo.CrossPlatformAPI.CrossPlatformService;
import com.example.tsldemo.auth.JwtUtil;


@SpringBootTest
@AutoConfigureMockMvc
class CrossPlatformControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private CrossPlatformService crossPlatformService;

    @MockitoBean
    private JwtUtil jwtUtil;


    @Test
    void linkedInPost_returnsPostId() throws Exception {

        when(jwtUtil.extractBusinessId(anyString()))
                .thenReturn(1);

        when(crossPlatformService.postToLinkedIn(eq(1), any()))
                .thenReturn("abc123");


        String json = """
        {
          "message":"Hello LinkedIn",
          "scheduledTime":null
        }
        """;


        mockMvc.perform(post("/linkedin/post")
                .header("Authorization", "Bearer token")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.PostId").value("abc123"));


        verify(crossPlatformService)
                .postToLinkedIn(eq(1), any());
    }
}