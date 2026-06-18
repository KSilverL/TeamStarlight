package com.example.tsldemo.DTOs.Error;

import java.util.List;

public record AgentError(
    List<Detail> detail
) {}
