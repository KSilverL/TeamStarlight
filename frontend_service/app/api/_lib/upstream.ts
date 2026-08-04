// Pulls the human-readable part out of a Java error response.
//
// Spring answers failures with a JSON envelope ({ timestamp, status, error, path }) and, for the
// endpoints that build an explanation worth showing, an { error } body of their own. Relaying the
// raw text put things like {"timestamp":"…","status":500,"error":"Internal Server Error"} in front
// of the user, which says nothing about what to fix. Non-JSON bodies pass through untouched.
export function extractJavaError(body: string): string {
  try {
    const parsed = JSON.parse(body);
    return parsed.message || parsed.error || body;
  } catch {
    return body;
  }
}
