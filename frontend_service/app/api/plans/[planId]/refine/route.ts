import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Regenerates a DRAFT plan in place from free-text feedback — same plan_id, still a draft.
//
// This is the satisfaction loop: "more Facebook, fewer promos, push harder in the final week"
// rewrites the whole schedule. For a single-slot tweak the caller should PATCH the item instead
// of regenerating everything.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ planId: string }> }
) {
  const { planId } = await params;
  const authHeader = request.headers.get("Authorization");
  const body = await request.json().catch(() => ({}));

  try {
    const upstream = await fetch(`${BACKEND_URL}/plans/${planId}/refine`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
    });

    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return Response.json(
        { error: data.error ?? "Could not revise this plan." },
        { status: upstream.status }
      );
    }
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
