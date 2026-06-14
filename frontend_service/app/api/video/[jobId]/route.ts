import { NextRequest } from "next/server";

const VIDEO_AGENT_URL =
  process.env.BRAND_VIDEO_AGENT_URL ?? "http://localhost:8001";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;

  try {
    const upstream = await fetch(`${VIDEO_AGENT_URL}/jobs/${jobId}`);

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await upstream.json();
    return new Response(
      JSON.stringify({ status: data.status, error: data.error ?? null }),
      { headers: { "Content-Type": "application/json" } }
    );
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Video agent unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
