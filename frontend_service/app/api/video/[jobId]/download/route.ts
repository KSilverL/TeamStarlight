import { NextRequest } from "next/server";

const VIDEO_AGENT_URL =
  process.env.BRAND_VIDEO_AGENT_URL ?? "http://localhost:8001";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;

  try {
    const upstream = await fetch(`${VIDEO_AGENT_URL}/download/${jobId}`);

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
      err instanceof Error ? err.message : "Video agent unreachable";
    return new Response(message, { status: 502 });
  }
}
