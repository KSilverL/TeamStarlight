import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const authHeader = request.headers.get("Authorization");
  // Optional body, carrying `draft_mode`. A confirm sent without one is still valid —
  // the plan keeps whatever mode it already has — so an unparseable body degrades to
  // an empty one rather than failing the confirm.
  const body = await request.json().catch(() => ({}));

  try {
    const upstream = await fetch(`${BACKEND_URL}/plans/${planId}/confirm`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
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