import { NextRequest } from "next/server";

const VIDEO_AGENT_URL =
  process.env.BRAND_VIDEO_AGENT_URL ?? "http://localhost:8081";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const taskId: string = body.taskId ?? "";
  const platform: string = body.platform ?? "";
  // Optional user-attached reference images (base64 data URLs), forwarded to the
  // Higgsfield backend for image-to-video. Ignored by the Remotion backends.
  const referenceImages: string[] = Array.isArray(body.referenceImages)
    ? body.referenceImages.filter((s: unknown): s is string => typeof s === "string").slice(0, 3)
    : [];

  if (!taskId.trim() || !platform.trim()) {
    return Response.json(
      { error: "taskId and platform are required" },
      { status: 400 }
    );
  }

  try {
    const upstream = await fetch(`${LLM_URL}/tasks/${taskId}/render-video`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform,
        ...(referenceImages.length > 0 ? { reference_images: referenceImages } : {}),
      }),
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const data = await upstream.json();
    return new Response(JSON.stringify({ jobId: data.job_id, status: data.status }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "LLM service unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
