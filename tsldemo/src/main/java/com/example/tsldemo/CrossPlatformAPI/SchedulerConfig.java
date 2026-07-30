package com.example.tsldemo.CrossPlatformAPI;

import java.util.concurrent.Executor;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

@Configuration
@EnableScheduling
public class SchedulerConfig {
    @Bean
    public TaskScheduler taskScheduler() {
        ThreadPoolTaskScheduler scheduler = new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(5);
        scheduler.initialize();
        return scheduler;
    }

    /** Separate pool for Instagram publishes, kept off {@link #taskScheduler()} on purpose.
     *
     * A publish occupies its thread for as long as Instagram takes to transcode — minutes, in the
     * worst case. Sharing the 5-thread scheduler pool would let a handful of concurrent publishes
     * starve the @Scheduled cron jobs (PlanScheduler's daily run among them) of threads.
     *
     * Queue capacity is deliberately small and rejection is caller-runs: if publishes are backed
     * up this far, blocking the request thread is a more honest signal than silently queueing work
     * the user is waiting on. */
    @Bean("instagramPublishExecutor")
    public Executor instagramPublishExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(8);
        executor.setQueueCapacity(16);
        executor.setThreadNamePrefix("ig-publish-");
        executor.setRejectedExecutionHandler(new java.util.concurrent.ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }

}