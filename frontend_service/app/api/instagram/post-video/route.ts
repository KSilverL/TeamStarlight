import { NextRequest } from "next/server";

const JAVA_BACKEND_URL = process.env.JAVA_BACKEND_URL ?? "http://backend:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const jobId: string = body.jobId ?? "";
  const caption: string = body.caption ?? "";

  if (!jobId.trim()) {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }

  try {
    const form = new FormData();
    form.append("job_id", jobId);
    form.append("caption", caption);

    const upstream = await fetch(`${JAVA_BACKEND_URL}/instagram/post-video`, {
      method: "POST",
      body: form,
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(JSON.stringify({ error: text }), {
        status: upstream.status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const mediaId = await upstream.text();
    return new Response(JSON.stringify({ mediaId }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Instagram backend unreachable";
    return new Response(JSON.stringify({ error: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}