package com.example.tsldemo.AgentAPI;

import java.util.Optional;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.TaskOwner;
import com.example.tsldemo.auth.JwtUtil;

/**
 * Decides whether a caller may touch a given run.
 *
 * <p>{@link BriefIdentity} settled which brand a run is CREATED against. This settles who may
 * read and steer it afterwards — the other half of the same problem. Without it, every
 * {@code /tasks/{id}/…} route treats the id itself as the credential: knowing one is enough to
 * read another brand's drafts and roundtable transcript, or to approve/discard their work.
 *
 * <p>The rule, and why it is shaped this way:
 * <ul>
 *   <li>A run started by an authenticated caller is <b>owned</b>. Only that business may touch it;
 *       anyone else gets 403, whether they are logged in as someone else or not logged in at all.</li>
 *   <li>A run started anonymously is <b>unowned</b> and stays open, which is exactly how it behaved
 *       before. It reads no brand profile and writes no learned preferences, so there is no tenant
 *       boundary to enforce — and refusing it would break anonymous use for no security gain.</li>
 * </ul>
 */
@Component
public class TaskAccess {

    private final TaskOwnerRepository owners;
    private final JwtUtil jwt;

    public TaskAccess(TaskOwnerRepository owners, JwtUtil jwt) {
        this.owners = owners;
        this.jwt = jwt;
    }

    /** Record who a newly-started run belongs to. A run with no verified identity gets no row. */
    public void remember(String taskId, String authHeader) {
        int businessId = jwt.extractBusinessId(authHeader);
        if (taskId == null || taskId.isBlank() || businessId <= 0) {
            return;
        }
        owners.save(new TaskOwner(taskId, businessId));
    }

    /**
     * Throw 403 unless this caller may act on {@code taskId}.
     *
     * <p>A missing row means "nobody claimed this run", which is permitted — see the class note.
     * The check is deliberately not "is the caller logged in": a logged-in caller has no more
     * right to someone else's run than an anonymous one.
     */
    public void assertMayAccess(String taskId, String authHeader) {
        Optional<TaskOwner> owner = owners.findById(taskId == null ? "" : taskId);
        if (owner.isEmpty() || owner.get().getBusinessId() == null) {
            return;  // unowned run — open, as it has always been
        }
        if (owner.get().getBusinessId() != jwt.extractBusinessId(authHeader)) {
            // Deliberately says nothing about whether the task exists: an error that distinguished
            // "not yours" from "no such task" would confirm ids for anyone probing.
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "not your task");
        }
    }
}
