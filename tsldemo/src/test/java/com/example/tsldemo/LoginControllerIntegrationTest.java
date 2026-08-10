package com.example.tsldemo;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.http.MediaType;

import com.example.tsldemo.LoginAPI.LoginService;
import com.example.tsldemo.auth.JwtUtil;


@SpringBootTest
@AutoConfigureMockMvc
class LoginControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private LoginService loginService;

    @MockitoBean
    private JwtUtil jwtUtil;


    @Test
    void login_success_returnsToken() throws Exception {

        Business business = new Business();
        business.setId(1);

        when(loginService.checkCredentials(
                "test@test.com",
                "password"
        )).thenReturn(business);


        when(jwtUtil.generateToken(1))
                .thenReturn("abc.jwt.token");


        String json = """
        {
          "email":"test@test.com",
          "password":"password"
        }
        """;


        mockMvc.perform(post("/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").value("abc.jwt.token"));
    }


    @Test
    void login_invalidCredentials_returns401() throws Exception {

        when(loginService.checkCredentials(
                anyString(),
                anyString()
        )).thenReturn(null);


        String json = """
        {
          "email":"wrong@test.com",
          "password":"wrongpassword"
        }
        """;


        mockMvc.perform(post("/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error")
                        .value("Invalid email or password"));
    }


    @Test
    void login_missingFields_returns400() throws Exception {

        String json = """
        {
          "email":"test@test.com"
        }
        """;


        mockMvc.perform(post("/login")
                .contentType(MediaType.APPLICATION_JSON)
                .content(json))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error")
                        .value("email and password are required"));
    }
}