import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// What a plan's slots have actually put on the content calendar, keyed by item id.
//
// The plan document itself only records that a slot was approved, which says nothing about
// whether anything was queued to publish. The plan view reads this alongside it so it can show
// real publish times, and offer to schedule the slots that produced none.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const authHeader = request.headers.get("Authorization");

  try {
    const upstream = await fetch(`${BACKEND_URL}/plans/${planId}/scheduled`, {
      headers: { ...(authHeader ? { Authorization: authHeader } : {}) },
    });

    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return Response.json(
        { error: data.error ?? "Failed to fetch scheduled posts for this plan" },
        { status: upstream.status }
      );
    }
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
