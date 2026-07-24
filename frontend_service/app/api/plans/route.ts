import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const authHeader = request.headers.get("Authorization");

  try {
    const upstream = await fetch(`${BACKEND_URL}/plans`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
    });

    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return Response.json({ error: data.error ?? "Failed to create plan" }, { status: upstream.status });
    }
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}

export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");
  const status = request.nextUrl.searchParams.get("status");

  try {
    const upstream = await fetch(
      `${BACKEND_URL}/plans${status ? `?status=${encodeURIComponent(status)}` : ""}`,
      { headers: { ...(authHeader ? { Authorization: authHeader } : {}) } }
    );

    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return Response.json({ error: data.error ?? "Failed to list plans" }, { status: upstream.status });
    }
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}