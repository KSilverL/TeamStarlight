package com.example.tsldemo;

import static org.mockito.Mockito.*;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import org.springframework.beans.factory.annotation.Autowired;

import com.example.tsldemo.CrossPlatformAPI.PlanScheduler;
import com.example.tsldemo.CrossPlatformAPI.PlanService;
import com.example.tsldemo.SignInAPI.BusinessRepository;


@SpringBootTest
class PlanSchedulerTest {


    @Autowired
    private PlanScheduler scheduler;


    @MockitoBean
    private PlanService planService;


    @MockitoBean
    private BusinessRepository businessRepository;



    @Test
    void runPlanCheck_executesDuePlanItem() {


        Business business = new Business();
        business.setId(1);
        business.setEmail("test@test.com");


        when(businessRepository.findAll())
                .thenReturn(List.of(business));


        when(planService.getDuePlans(
                any(LocalDate.class),
                eq(1)))
                .thenReturn(Map.of(
                    "items",
                    List.of(
                        Map.of(
                            "plan_id","plan123",
                            "item",
                            Map.of(
                                "item_id",
                                "item123"
                            )
                        )
                    )
                ));


        when(planService.executePlanItem(
                eq("plan123"),
                eq("item123"),
                isNull()
        ))
        .thenReturn(Map.of(
                "task",
                Map.of(
                        "task_id",
                        "task123"
                )
        ));



        scheduler.runPlanCheck();


        verify(planService)
                .executePlanItem(
                        "plan123",
                        "item123",
                        null
                );
    }
}