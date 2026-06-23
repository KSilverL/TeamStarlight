import { NextRequest } from "next/server";

// TEXT_AGENT_URL points at the main LLM service (/generate-text).
// Falls back to BRAND_AGENT_URL for the demo brand-agent, then localhost.
const TEXT_AGENT_URL =
  process.env.TEXT_AGENT_URL ??
  process.env.BRAND_AGENT_URL ??
  "http://localhost:8080";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const prompt: string = body.prompt ?? "";
  const platform: string = body.platform ?? "linkedin";

  if (!prompt.trim()) {
    return new Response(JSON.stringify({ error: "prompt is required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const upstream = await fetch(`${TEXT_AGENT_URL}/generate-text`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, platform }),
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await upstream.json();
    return new Response(
      JSON.stringify({ text: data.text, platform: data.platform }),
      { headers: { "Content-Type": "application/json" } }
    );
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Text backend unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
