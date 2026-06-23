import { NextRequest } from "next/server";

const BRAND_AGENT_URL = process.env.BRAND_AGENT_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const prompt: string = body.prompt ?? "";
  const history: unknown = body.history ?? undefined;

  if (!prompt.trim()) {
    return new Response(JSON.stringify({ error: "prompt is required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const upstream = await fetch(`${BRAND_AGENT_URL}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, ...(history ? { history } : {}) }),
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await upstream.json();
    return new Response(JSON.stringify({ html: data.html }), {
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Brand agent unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
