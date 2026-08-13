package com.example.tsldemo.AgentAPI;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import com.example.tsldemo.TaskOwner;
import com.example.tsldemo.auth.JwtUtil;

/**
 * Who may read and steer a run.
 *
 * <p>The LLM service has no authentication of its own, so before this existed a task id WAS the
 * credential: anyone holding one could read that run's drafts and roundtable transcript, and could
 * approve or discard another business's work. These tests pin the boundary, including the case
 * that makes it worth having — a caller who is perfectly well logged in, just as somebody else.
 */
class TaskAccessTest {

    private static final String SECRET = "test-secret-that-is-at-least-32-bytes-long";

    private final JwtUtil jwt = new JwtUtil(SECRET, RestClient.builder().build());
    private final Map<String, TaskOwner> rows = new HashMap<>();
    private final TaskAccess access = new TaskAccess(new InMemoryOwners(rows), jwt);

    private String tokenFor(int businessId) {
        return "Bearer " + jwt.generateToken(businessId);
    }

    @Test
    @DisplayName("the business that started a run may use it")
    void ownerMayAccess() {
        access.remember("t1", tokenFor(42));

        assertThatCode(() -> access.assertMayAccess("t1", tokenFor(42))).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("another logged-in business may NOT — this is the whole point")
    void otherBusinessIsRefused() {
        access.remember("t1", tokenFor(42));

        assertThatThrownBy(() -> access.assertMayAccess("t1", tokenFor(43)))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("403");
    }

    @Test
    @DisplayName("an anonymous caller may not touch an owned run either")
    void anonymousIsRefusedAnOwnedRun() {
        access.remember("t1", tokenFor(42));

        assertThatThrownBy(() -> access.assertMayAccess("t1", null))
                .isInstanceOf(ResponseStatusException.class);
    }

    @Test
    @DisplayName("a forged token does not open an owned run")
    void forgedTokenIsRefused() {
        access.remember("t1", tokenFor(42));
        JwtUtil attacker = new JwtUtil("a-completely-different-secret-key-32bytes",
                RestClient.builder().build());

        assertThatThrownBy(() ->
                access.assertMayAccess("t1", "Bearer " + attacker.generateToken(42)))
                .isInstanceOf(ResponseStatusException.class);
    }

    @Test
    @DisplayName("a run started anonymously stays open, exactly as it behaved before")
    void anonymousRunsAreUnowned() {
        // No identity means no brand profile and no learned preferences — there is no tenant to
        // protect, and refusing these would break anonymous use for no security gain.
        access.remember("t2", null);

        assertThat(rows).doesNotContainKey("t2");
        assertThatCode(() -> access.assertMayAccess("t2", null)).doesNotThrowAnyException();
        assertThatCode(() -> access.assertMayAccess("t2", tokenFor(9))).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("an unknown task id is not treated as owned")
    void unknownTaskIsOpen() {
        assertThatCode(() -> access.assertMayAccess("never-seen", tokenFor(1)))
                .doesNotThrowAnyException();
        assertThatCode(() -> access.assertMayAccess(null, null)).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("a forged token cannot CLAIM a run either")
    void forgedTokenCannotClaim() {
        JwtUtil attacker = new JwtUtil("a-completely-different-secret-key-32bytes",
                RestClient.builder().build());

        access.remember("t3", "Bearer " + attacker.generateToken(7));

        assertThat(rows).doesNotContainKey("t3");
    }

    /** Minimal stand-in for the JPA repository — only findById/save are used. */
    private record InMemoryOwners(Map<String, TaskOwner> rows) implements TaskOwnerRepository {
        @Override
        public Optional<TaskOwner> findById(String id) {
            return Optional.ofNullable(rows.get(id));
        }

        @Override
        public <S extends TaskOwner> S save(S entity) {
            rows.put(entity.getTaskId(), entity);
            return entity;
        }

        // The rest of JpaRepository is unused here.
        @Override public void flush() { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> S saveAndFlush(S e) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> java.util.List<S> saveAllAndFlush(Iterable<S> e) { throw new UnsupportedOperationException(); }
        @Override public void deleteAllInBatch(Iterable<TaskOwner> e) { throw new UnsupportedOperationException(); }
        @Override public void deleteAllByIdInBatch(Iterable<String> i) { throw new UnsupportedOperationException(); }
        @Override public void deleteAllInBatch() { throw new UnsupportedOperationException(); }
        @Override public TaskOwner getOne(String id) { throw new UnsupportedOperationException(); }
        @Override public TaskOwner getById(String id) { throw new UnsupportedOperationException(); }
        @Override public TaskOwner getReferenceById(String id) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> java.util.List<S> findAll(org.springframework.data.domain.Example<S> ex) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> java.util.List<S> findAll(org.springframework.data.domain.Example<S> ex, org.springframework.data.domain.Sort s) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> java.util.List<S> saveAll(Iterable<S> e) { throw new UnsupportedOperationException(); }
        @Override public java.util.List<TaskOwner> findAll() { throw new UnsupportedOperationException(); }
        @Override public java.util.List<TaskOwner> findAllById(Iterable<String> i) { throw new UnsupportedOperationException(); }
        @Override public java.util.List<TaskOwner> findAll(org.springframework.data.domain.Sort s) { throw new UnsupportedOperationException(); }
        @Override public org.springframework.data.domain.Page<TaskOwner> findAll(org.springframework.data.domain.Pageable p) { throw new UnsupportedOperationException(); }
        @Override public boolean existsById(String id) { throw new UnsupportedOperationException(); }
        @Override public long count() { throw new UnsupportedOperationException(); }
        @Override public void deleteById(String id) { throw new UnsupportedOperationException(); }
        @Override public void delete(TaskOwner e) { throw new UnsupportedOperationException(); }
        @Override public void deleteAllById(Iterable<? extends String> i) { throw new UnsupportedOperationException(); }
        @Override public void deleteAll(Iterable<? extends TaskOwner> e) { throw new UnsupportedOperationException(); }
        @Override public void deleteAll() { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> Optional<S> findOne(org.springframework.data.domain.Example<S> ex) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> org.springframework.data.domain.Page<S> findAll(org.springframework.data.domain.Example<S> ex, org.springframework.data.domain.Pageable p) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> long count(org.springframework.data.domain.Example<S> ex) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner> boolean exists(org.springframework.data.domain.Example<S> ex) { throw new UnsupportedOperationException(); }
        @Override public <S extends TaskOwner, R> R findBy(org.springframework.data.domain.Example<S> ex, java.util.function.Function<org.springframework.data.repository.query.FluentQuery.FetchableFluentQuery<S>, R> fn) { throw new UnsupportedOperationException(); }
    }
}
