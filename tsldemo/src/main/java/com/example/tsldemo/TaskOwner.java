package com.example.tsldemo;

import java.time.Instant;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import lombok.Getter;
import lombok.Setter;

/**
 * Who a newsroom run belongs to.
 *
 * <p>Without this, a task id is a bearer token: the LLM service has no authentication of its own,
 * so anyone who knows (or guesses) an id can read that run's drafts, its roundtable transcript and
 * its audio, and can submit verdicts on it. This is the same rule the scheduled-post table already
 * enforces with {@code findByIdAndBusinessId} — never look a resource up by id alone.
 *
 * <p>Rows are written only for runs started WITH a verified identity. A run started anonymously
 * has no row and stays open to anyone holding its id, exactly as it was before — an anonymous run
 * carries no brand profile and no learned preferences, so there is no tenant to protect, and
 * requiring a login to generate anything is a product decision rather than a security fix.
 */
@Getter
@Setter
@Entity
public class TaskOwner {

    /** The task/session id the LLM service issued. */
    @Id
    private String taskId;

    private Integer businessId;

    private Instant createdAt = Instant.now();

    public TaskOwner() {
    }

    public TaskOwner(String taskId, Integer businessId) {
        this.taskId = taskId;
        this.businessId = businessId;
        this.createdAt = Instant.now();
    }
}
