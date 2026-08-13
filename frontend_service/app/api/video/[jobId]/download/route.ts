import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Streams the finished MP4 through Next.js so the browser never needs to reach
// the LLM service's internal (e.g. Docker-network) hostname directly.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;

  try {
    const upstream = await fetch(`${BACKEND_URL}/video-jobs/${jobId}/download`);

    if (!upstream.ok) {
      return new Response("Video not available", { status: upstream.status });
    }

    // Stream the MP4 body directly — avoids buffering the whole file in memory
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "video/mp4",
        "Content-Disposition": `inline; filename="${jobId}.mp4"`,
      },
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "LLM service unreachable";
    return new Response(message, { status: 502 });
  }
}
