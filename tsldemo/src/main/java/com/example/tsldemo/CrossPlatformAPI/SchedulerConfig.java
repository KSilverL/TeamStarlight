package com.example.tsldemo.CrossPlatformAPI;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;

/**
 * The pool behind every {@code @Scheduled} method — the daily plan check and the scheduled-post
 * sweeper.
 *
 * <p>This pool no longer holds the schedule itself. It used to also carry one pending timer per
 * scheduled post, which meant the queue *was* the schedule and everything in it was lost on
 * restart; posts now live in the {@code scheduled_post} table and the pool only runs the
 * recurring job that reads it.
 */
@Configuration
@EnableScheduling
public class SchedulerConfig {
    @Bean
    public TaskScheduler taskScheduler() {
        ThreadPoolTaskScheduler scheduler = new ThreadPoolTaskScheduler();
        scheduler.setPoolSize(5);
        // Named so a stuck publish is identifiable in a thread dump rather than showing up as
        // an anonymous pool-N-thread-M alongside every other scheduled job.
        scheduler.setThreadNamePrefix("starlight-sched-");
        scheduler.initialize();
        return scheduler;
    }

}