package com.example.tsldemo;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;


import com.example.tsldemo.CrossPlatformAPI.InstagramAPIService;


@SpringBootTest
@AutoConfigureMockMvc
class InstagramAPIControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;


    @MockitoBean
    private InstagramAPIService instagramAPIService;


    @Test
    void postVideo_returnsMediaId() throws Exception {

        when(instagramAPIService.postVideo(
                anyString(),
                anyString()
        )).thenReturn("media123");


        mockMvc.perform(multipart("/instagram/post-video")
                .param("job_id", "job123")
                .param("caption", "My first Instagram video"))
                .andExpect(status().isOk())
                .andExpect(content().string("media123"));
    }
}