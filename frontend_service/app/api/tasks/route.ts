import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();

  if (!body.topic?.trim()) {
    return Response.json({ error: "topic is required" }, { status: 400 });
  }
  if (!Array.isArray(body.target_platforms) || body.target_platforms.length === 0) {
    return Response.json(
      { error: "target_platforms must be a non-empty array" },
      { status: 400 }
    );
  }

  // The token is what tells the backend which brand this run belongs to. Without it the run is a
  // cold start (no brand voice, no learned preferences) — which is what an anonymous caller gets,
  // by design. Note the backend re-derives the identity from the token and DISCARDS any
  // `business_id` in the body, so there is nothing to gain by sending one from here.
  const authHeader = request.headers.get("Authorization");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authHeader) headers.Authorization = authHeader;

  try {
    const upstream = await fetch(`${BACKEND_URL}/tasks`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
