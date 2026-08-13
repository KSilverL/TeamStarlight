import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;
  const body = await request.json();

  if (!body.verdicts || typeof body.verdicts !== "object") {
    return Response.json({ error: "verdicts object is required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}/tasks/${taskId}/review`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // See the note in ../route.ts: the backend checks task ownership on this call.
        ...(request.headers.get("Authorization")
          ? { Authorization: request.headers.get("Authorization") as string }
          : {}),
      },
      body: JSON.stringify(body),
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
