import { NextRequest } from "next/server";

const VIDEO_AGENT_URL =
  process.env.BRAND_VIDEO_AGENT_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const brief: string = body.brief ?? "";
  const history: unknown = body.history ?? undefined;

  if (!brief.trim()) {
    return new Response(JSON.stringify({ error: "brief is required" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const upstream = await fetch(`${VIDEO_AGENT_URL}/generate-video`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brief, ...(history ? { history } : {}) }),
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await upstream.json();
    return new Response(JSON.stringify({ jobId: data.job_id }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Video agent unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
