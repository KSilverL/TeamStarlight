import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const authHeader = request.headers.get("Authorization");

  try {
    const upstream = await fetch(`${BACKEND_URL}/plans/${planId}/confirm`, {
      method: "POST",
      headers: { ...(authHeader ? { Authorization: authHeader } : {}) },
    });

    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return Response.json({ error: data.error ?? "Failed to confirm plan" }, { status: upstream.status });
    }
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}