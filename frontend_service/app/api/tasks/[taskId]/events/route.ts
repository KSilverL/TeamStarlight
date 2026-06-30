import { NextRequest } from "next/server";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

// Force dynamic so Next.js never caches or buffers this streaming route.
export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;

  try {
    const upstream = await fetch(`${LLM_URL}/tasks/${taskId}/events`, {
      headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
    });

    if (!upstream.ok || !upstream.body) {
      return Response.json(
        { error: "SSE stream unavailable" },
        { status: upstream.status || 502 }
      );
    }

    // Pipe the upstream SSE body directly to the browser — no buffering.
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
