package com.example.tsldemo.AgentAPI;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import com.example.tsldemo.auth.JwtUtil;

/**
 * The tenant boundary.
 *
 * `business_id` picks which brand's voice profile a run reads and writes. If a caller can choose
 * it, they can read another brand's tone rules and poison them — so "the body's value is never
 * trusted" is the property under test here, including in the awkward cases (no token, expired
 * token, forged token) where there is nothing to replace it with.
 */
class BriefIdentityTest {

    private static final String SECRET = "test-secret-that-is-at-least-32-bytes-long";

    private final JwtUtil jwt = new JwtUtil(SECRET, RestClient.builder().build());
    private final BriefIdentity identity = new BriefIdentity(jwt);

    private static Map<String, Object> brief(Object... identityFields) {
        Map<String, Object> brief = new LinkedHashMap<>();
        brief.put("topic", "ethiopia harvest");
        for (int i = 0; i < identityFields.length; i += 2) {
            brief.put(String.valueOf(identityFields[i]), identityFields[i + 1]);
        }
        return brief;
    }

    private String tokenFor(int businessId) {
        return "Bearer " + jwt.generateToken(businessId);
    }

    @Test
    @DisplayName("the verified business id replaces whatever the body claimed")
    void verifiedIdentityWins() {
        Map<String, Object> stamped =
                identity.stamp(brief("business_id", "999", "user_id", "999"), tokenFor(42));

        assertThat(stamped.get("business_id")).isEqualTo("42");
        assertThat(stamped.get("user_id")).isEqualTo("42");
        assertThat(stamped.get("topic")).isEqualTo("ethiopia harvest");
    }

    @Test
    @DisplayName("with no token, a body-supplied business id is DROPPED rather than kept")
    void unauthenticatedCannotClaimABrand() {
        // The dangerous case: there is no verified value to overwrite with, so anything that
        // merely "overwrites when authenticated" would leave the caller's own claim standing.
        Map<String, Object> stamped = identity.stamp(brief("business_id", "999"), null);

        assertThat(stamped).doesNotContainKey("business_id");
        assertThat(stamped).doesNotContainKey("user_id");
        assertThat(stamped.get("topic")).isEqualTo("ethiopia harvest");
    }

    @Test
    @DisplayName("a forged token is treated as no token at all")
    void forgedTokenGrantsNothing() {
        // Signed with a different key — decodable, but not ours. A layer that only READ the claim
        // (rather than verifying the signature) would happily hand this caller business 999.
        JwtUtil attacker = new JwtUtil("a-completely-different-secret-key-32bytes",
                RestClient.builder().build());
        String forged = "Bearer " + attacker.generateToken(999);

        Map<String, Object> stamped = identity.stamp(brief("business_id", "999"), forged);

        assertThat(stamped).doesNotContainKey("business_id");
    }

    @Test
    @DisplayName("a malformed Authorization header grants nothing")
    void malformedHeaderGrantsNothing() {
        for (String header : new String[] {"", "Bearer", "Bearer not.a.jwt", "Basic abc", "42"}) {
            assertThat(identity.stamp(brief("business_id", "999"), header))
                    .as("header %s", header)
                    .doesNotContainKey("business_id");
        }
    }

    @Test
    @DisplayName("the caller's brief is not mutated in place")
    void doesNotMutateTheInput() {
        Map<String, Object> original = brief("business_id", "999");

        identity.stamp(original, tokenFor(7));

        assertThat(original.get("business_id")).isEqualTo("999");
    }

    @Test
    @DisplayName("a null body is handled without blowing up")
    void nullBriefIsSafe() {
        assertThat(identity.stamp(null, tokenFor(7))).containsEntry("business_id", "7");
        assertThat(identity.stamp(null, null)).isEmpty();
    }
}
