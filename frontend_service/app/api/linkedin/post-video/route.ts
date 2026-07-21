import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Uploads a finished video render job to LinkedIn and publishes it — synchronous end-to-end
// (upload -> LinkedIn processing wait -> publish), so this can take noticeably longer than the
// text-only /api/linkedin/post. No special timeout handling needed: this app runs as a
// long-lived Node server, not a short-lived serverless function.
export async function POST(request: NextRequest) {
  const body = await request.json();
  const authHeader = request.headers.get("Authorization");

  if (!body.jobId || typeof body.jobId !== "string") {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }
  if (!body.message || typeof body.message !== "string") {
    return Response.json({ error: "message is required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/linkedin/post-video`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({
        jobId: body.jobId,
        message: body.message,
        title: typeof body.title === "string" ? body.title : null,
      }),
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: text || "Failed to post video to LinkedIn" },
        { status: upstream.status }
      );
    }

    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
