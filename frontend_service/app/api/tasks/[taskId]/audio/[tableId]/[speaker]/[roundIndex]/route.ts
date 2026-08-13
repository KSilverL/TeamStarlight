import { NextRequest } from "next/server";

// Routed through the Java backend, which is where identity is VERIFIABLE (it holds the JWT
// signing key) and therefore where the brand a run reads and writes gets decided. Talking to the
// Python service directly would mean `business_id` is whatever the caller typed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// One roundtable turn's TTS clip. The `agent_utterance_audio` SSE event used to carry the mp3
// inline as base64; it now carries an `audio_url` pointing here, so the event stream (which is
// replayed on every reconnect) stays small. This path deliberately mirrors the upstream one, so
// the URL on the event maps to this proxy by prefixing "/api" — the same mirror the sibling
// /api/tasks/[taskId]/events route already uses.
export async function GET(
  request: NextRequest,
  {
    params,
  }: {
    params: Promise<{
      taskId: string;
      tableId: string;
      speaker: string;
      roundIndex: string;
    }>;
  }
) {
  const { taskId, tableId, speaker, roundIndex } = await params;

  try {
    // An <audio> element sets no headers, so the token arrives as `?access_token=`. Turn it
    // back into an Authorization header, keeping the credential out of the upstream request line.
    const auth = request.headers.get("Authorization");
    const accessToken = request.nextUrl.searchParams.get("access_token");
    const headers: Record<string, string> = {};
    if (auth) headers.Authorization = auth;
    else if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

    const upstream = await fetch(
      `${BACKEND_URL}/tasks/${encodeURIComponent(taskId)}/audio/${encodeURIComponent(
        tableId
      )}/${encodeURIComponent(speaker)}/${encodeURIComponent(roundIndex)}`,
      { headers }
    );

    if (!upstream.ok) {
      // 404 here means "never synthesized, or evicted from the bounded cache" — the caller
      // just gets no audio for that turn, which is how TTS failures already degrade.
      return new Response("Audio not available", { status: upstream.status });
    }

    // Stream the clip through rather than buffering it.
    return new Response(upstream.body, {
      headers: { "Content-Type": "audio/mpeg", "Cache-Control": "no-store" },
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "LLM service unreachable";
    return new Response(message, { status: 502 });
  }
}
