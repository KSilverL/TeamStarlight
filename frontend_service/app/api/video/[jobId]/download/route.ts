import { NextRequest } from "next/server";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

// Streams the finished MP4 through Next.js so the browser never needs to reach
// the LLM service's internal (e.g. Docker-network) hostname directly.
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;

  try {
    const upstream = await fetch(`${LLM_URL}/video-jobs/${jobId}/download`);

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
