package com.example.tsldemo;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import com.example.tsldemo.CrossPlatformAPI.PlanService;
import com.example.tsldemo.auth.JwtUtil;


@SpringBootTest
@AutoConfigureMockMvc
class PlanControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;


    @MockitoBean
    private PlanService planService;


    @MockitoBean
    private JwtUtil jwtUtil;


    @Test
    void createPlan_returnsPlan() throws Exception {

        when(jwtUtil.extractBusinessId(anyString()))
                .thenReturn(1);


        when(planService.createPlan(eq(1), anyMap()))
                .thenReturn(Map.of(
                        "plan_id", "plan123",
                        "status", "draft"
                ));


        String json = """
        {
          "goal":"Launch book shop",
          "platforms":["linkedin"]
        }
        """;


        mockMvc.perform(post("/plans")
                .header("Authorization", "Bearer token")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.plan_id")
                        .value("plan123"));
    }



    @Test
    void getPlan_ownedByBusiness_returnsPlan() throws Exception {

        when(jwtUtil.extractBusinessId(anyString()))
                .thenReturn(1);


        when(planService.getPlan("plan123"))
                .thenReturn(Map.of(
                        "plan_id","plan123",
                        "business_id",1
                ));


        mockMvc.perform(get("/plans/plan123")
                .header("Authorization","Bearer token"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.plan_id")
                        .value("plan123"));
    }



    @Test
    void getPlan_wrongOwner_returns403() throws Exception {

        when(jwtUtil.extractBusinessId(anyString()))
                .thenReturn(1);


        when(planService.getPlan("plan123"))
                .thenReturn(Map.of(
                        "plan_id","plan123",
                        "business_id",99
                ));


        mockMvc.perform(get("/plans/plan123")
                .header("Authorization","Bearer token"))
                .andExpect(status().isForbidden());
    }



    @Test
    void confirmPlan_returnsUpdatedPlan() throws Exception {

        when(jwtUtil.extractBusinessId(anyString()))
                .thenReturn(1);


        when(planService.getPlan("plan123"))
                .thenReturn(Map.of(
                        "business_id",1
                ));


        when(planService.confirmPlan("plan123"))
                .thenReturn(Map.of(
                        "status","active"
                ));


        mockMvc.perform(post("/plans/plan123/confirm")
                .header("Authorization","Bearer token"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status")
                        .value("active"));
    }



    @Test
    void clarifyPlan_returnsResponse() throws Exception {

        when(jwtUtil.extractBusinessId(anyString()))
                .thenReturn(1);


        when(planService.clarifyPlan(eq(1), anyMap()))
                .thenReturn(Map.of(
                        "question",
                        "What is your audience?"
                ));


        mockMvc.perform(post("/plans/clarify")
                .header("Authorization","Bearer token")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                {
                  "answer":"small businesses"
                }
                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.question")
                        .value("What is your audience?"));
    }
}