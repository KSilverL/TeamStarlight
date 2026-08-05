import { NextRequest } from "next/server";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

// Revises one platform's video storyboard from the user's feedback, proxying the LLM service's
// /tasks/{taskId}/regenerate-storyboard. Only the storyboard changes — the approved copy is left
// alone, which is the whole point of having this separate from the human gate's reject path.
//
// Deliberately NOT under /api/video: that path's next segment is the [jobId] dynamic route, so a
// storyboard revision sitting there would read as a render job id.

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const taskId: string = body.taskId ?? "";
  const platform: string = body.platform ?? "";
  const feedback: string = body.feedback ?? "";

  if (!taskId.trim() || !platform.trim()) {
    return Response.json({ error: "taskId and platform are required" }, { status: 400 });
  }
  if (!feedback.trim()) {
    return Response.json(
      { error: "Say what should change about the storyboard." },
      { status: 400 }
    );
  }

  try {
    const upstream = await fetch(`${LLM_URL}/tasks/${taskId}/regenerate-storyboard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, feedback: feedback.trim() }),
    });

    const text = await upstream.text();
    if (!upstream.ok) {
      // The LLM service answers errors as {"error": "..."} (its ApiError handler), so surface
      // that message rather than the raw envelope; fall back to the body for anything else.
      let message = text;
      try {
        message = JSON.parse(text).error ?? text;
      } catch {
        // non-JSON body — keep it verbatim
      }
      return Response.json(
        { error: message || "Could not revise the storyboard." },
        { status: upstream.status }
      );
    }

    const data = JSON.parse(text);
    return Response.json({ storyboard: data.video_storyboard });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
