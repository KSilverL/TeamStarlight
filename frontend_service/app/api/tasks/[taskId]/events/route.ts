import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Force dynamic so Next.js never caches or buffers this streaming route.
export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;

  // Resume marker. Every upstream frame carries an `id:`, so on an automatic reconnect the
  // browser's EventSource sends back the last id it saw as `Last-Event-ID` and the service
  // replays only what came after it. That only works if this proxy FORWARDS the header —
  // drop it and the resume silently never engages: no error anywhere, just a full replay of
  // the whole event log (audio-free now, but still every turn) on every reconnect.
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Cache-Control": "no-cache",
  };
  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) headers["Last-Event-ID"] = lastEventId;

  // EventSource cannot set headers, so the browser passes its token as `?access_token=`. Convert
  // it back to a normal Authorization header here, keeping the credential out of the upstream
  // request line — the backend's ownership check needs it to let an owned run's stream through.
  const authHeader = request.headers.get("Authorization");
  const accessToken = request.nextUrl.searchParams.get("access_token");
  if (authHeader) headers.Authorization = authHeader;
  else if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  try {
    const upstream = await fetch(`${BACKEND_URL}/tasks/${taskId}/events`, { headers });

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
