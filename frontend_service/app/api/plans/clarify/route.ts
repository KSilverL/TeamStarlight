import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// The pre-generation step: propose a cadence and ask up to 3 questions whose answers would
// tailor the plan, BEFORE any dated schedule exists.
//
// Goes through Java rather than straight to the LLM service, because Java stamps business_id
// from the JWT — that is what folds the brand-voice profile into the proposal.
export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");
  const body = await request.json().catch(() => ({}));

  try {
    const upstream = await fetch(`${BACKEND_URL}/plans/clarify`, {
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
        { error: data.error ?? "Could not work out what to ask about this campaign." },
        { status: upstream.status }
      );
    }
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
