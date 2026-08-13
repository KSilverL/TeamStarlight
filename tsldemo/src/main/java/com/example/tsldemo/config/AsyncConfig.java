package com.example.tsldemo.config;

import java.util.concurrent.Executor;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

/**
 * The pool behind {@code @Async} — today, newsroom runs kicked off when an intake completes.
 *
 * <p>Deliberately NOT the {@code taskScheduler} pool from {@link
 * com.example.tsldemo.CrossPlatformAPI.SchedulerConfig}. That one runs the recurring sweepers that
 * publish scheduled posts; a newsroom run occupies its thread for minutes (it waits at the human
 * gate), so sharing would let a few runs starve the publishing schedule.
 *
 * <p>The queue is bounded and overflow runs on the caller: an unbounded queue would accept work
 * forever and fail as an out-of-memory error long after the cause, while CallerRuns pushes the
 * delay back onto whoever is submitting — the honest signal that the system is saturated.
 */
@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean(name = "newsroomExecutor")
    public Executor newsroomExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(8);
        executor.setQueueCapacity(50);
        // Named so a run stuck at the gate is identifiable in a thread dump.
        executor.setThreadNamePrefix("starlight-newsroom-");
        executor.setRejectedExecutionHandler(
                new java.util.concurrent.ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }
}
