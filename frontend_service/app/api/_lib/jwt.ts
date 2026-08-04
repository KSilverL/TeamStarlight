// Pulls the businessId out of the app's JWT.
//
// The LinkedIn endpoints let the Java backend derive businessId from the Authorization
// header, but the Meta endpoints take it as a request-body value instead. To keep the
// browser contract identical (it only ever holds the JWT, never a raw businessId), the Meta
// proxy routes decode it here and supply it to Java.
//
// LoginController signs the token with businessId in the standard `sub` (subject) claim
// (see JwtUtil.generateToken). We only READ that claim — the signature is not verified here.
// That matches the trust level the Java Meta endpoints already assume (they trust the
// body-supplied businessId outright), so this is not a new trust gap.
export function decodeBusinessId(authHeader: string | null): number | null {
  if (!authHeader || !authHeader.startsWith("Bearer ")) return null;
  const token = authHeader.slice("Bearer ".length).trim();

  const parts = token.split(".");
  if (parts.length !== 3) return null;

  try {
    // JWT segments are base64url; Node's base64 decoder needs the URL-safe chars swapped
    // back and the padding restored before it will decode cleanly.
    let b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    b64 += "=".repeat((4 - (b64.length % 4)) % 4);

    const payload = JSON.parse(Buffer.from(b64, "base64").toString("utf8"));
    const businessId = Number(payload.sub);
    return Number.isInteger(businessId) ? businessId : null;
  } catch {
    return null;
  }
}
