import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;

  try {
    // The caller's token decides whether they may touch this run at all — the backend refuses a
    // task owned by another business. Forwarding it is what makes an owned run reachable by its
    // owner; dropping it would 403 the very person who started it.
    const auth = request.headers.get("Authorization");
    const upstream = await fetch(`${BACKEND_URL}/tasks/${taskId}`, {
      headers: auth ? { Authorization: auth } : {},
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
