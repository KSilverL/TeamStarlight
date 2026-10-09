import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed — and this is the
// call that WRITES the learned brand voice, so that would let anyone train anyone's profile.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;
  const body = await request.json();

  if (typeof body.learn !== "boolean") {
    return Response.json({ error: "learn boolean is required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}/tasks/${taskId}/confirm-learning`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // See the note in ../route.ts: the backend checks task ownership on this call.
        ...(request.headers.get("Authorization")
          ? { Authorization: request.headers.get("Authorization") as string }
          : {}),
      },
      body: JSON.stringify({ learn: body.learn }),
    });
    // Status passes through untouched: 409 ("task is not complete") and 403 (not your run) each
    // mean something specific to the caller, and the card renders them differently.
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
