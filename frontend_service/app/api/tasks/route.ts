import { NextRequest } from "next/server";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

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

  try {
    const upstream = await fetch(`${LLM_URL}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
