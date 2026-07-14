import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const authHeader = request.headers.get("Authorization");

  if (!body.message || typeof body.message !== "string") {
    return Response.json({ error: "message is required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/linkedin/post`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({ message: body.message }),
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: text || "Failed to post to LinkedIn" },
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
