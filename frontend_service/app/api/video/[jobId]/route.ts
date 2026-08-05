import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;

  try {
    const upstream = await fetch(`${BACKEND_URL}/video-jobs/${jobId}`);

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await upstream.json();
    return new Response(
      JSON.stringify({
        status: data.status,
        error: data.error ?? null,
        // The storyboard itself was already delivered on the result/final SSE
        // event before the render was even triggered — the poll response only
        // needs to tell the card when (and where) the finished MP4 is.
        downloadUrl: data.status === "done" ? `/api/video/${jobId}/download` : null,
      }),
      { headers: { "Content-Type": "application/json" } }
    );
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "LLM service unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
