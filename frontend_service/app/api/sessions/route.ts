import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/api/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "text", opening_input: body.opening_input ?? null }),
    });

    const data = await upstream.json();

    if (!upstream.ok) {
      return new Response(JSON.stringify({ error: data.error ?? "Session creation failed" }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ session_id: data.session_id }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Java service unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
