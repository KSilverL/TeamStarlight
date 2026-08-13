package com.example.tsldemo.AgentAPI;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.example.tsldemo.auth.JwtUtil;

/**
 * Decides who a creative brief belongs to — and refuses to let the caller decide it for us.
 *
 * `business_id` and `user_id` are not descriptive metadata. Downstream they select which brand's
 * voice profile and which user's learned preferences the run reads AND writes. A caller that can
 * set them freely can read another brand's tone rules, and can poison them. Taking them from the
 * request body — which is what happens when nothing sits in front of the LLM service — makes every
 * tenant boundary in the system advisory.
 *
 * So the rule here is: whatever the body said is DROPPED, and the values are re-derived from the
 * signed token. The signing key lives in this application (see {@link JwtUtil}), which is why this
 * has to happen here and cannot be delegated to a layer that can only decode.
 *
 * An unauthenticated caller gets no identity at all rather than a rejection: the LLM service
 * treats a brief with no `business_id` as a cold start (steer on tone alone, never touch the
 * store), which is a safe, already-supported path. Requiring a login to generate anything is a
 * product decision, not one to smuggle in through a security fix.
 */
@Component
public class BriefIdentity {

    static final String BUSINESS_ID = "business_id";
    static final String USER_ID = "user_id";

    private final JwtUtil jwt;

    public BriefIdentity(JwtUtil jwt) {
        this.jwt = jwt;
    }

    /**
     * Return a copy of {@code brief} whose identity fields are the caller's verified ones.
     *
     * @param authHeader the raw `Authorization` header; null/absent/expired/forged all mean
     *                   "no identity", because {@link JwtUtil#extractBusinessId} answers -1 for
     *                   every one of them rather than throwing.
     */
    public Map<String, Object> stamp(Map<String, Object> brief, String authHeader) {
        Map<String, Object> stamped = new LinkedHashMap<>();
        if (brief != null) {
            stamped.putAll(brief);
        }

        // Unconditionally, BEFORE looking at the token: an unauthenticated request must not be
        // able to keep a business_id it supplied itself just because there is nothing to replace
        // it with. Dropping first and adding back only what we verified is what makes that true.
        stamped.remove(BUSINESS_ID);
        stamped.remove(USER_ID);

        int businessId = jwt.extractBusinessId(authHeader);
        if (businessId > 0) {
            // One account is one business here (the token's subject IS the business id), so the
            // brand-voice channel and the per-user channel key on the same identity.
            stamped.put(BUSINESS_ID, String.valueOf(businessId));
            stamped.put(USER_ID, String.valueOf(businessId));
        }
        return stamped;
    }
}
