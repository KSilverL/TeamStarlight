package com.example.tsldemo.DTOs.Error;

import java.util.List;

public record Detail(
    String type,
    List<String> loc,
    String msg,
    String input
) {}
