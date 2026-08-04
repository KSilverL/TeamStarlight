import { NextRequest } from "next/server";

// Goes straight to the LLM service, like /api/tasks and unlike /api/plans/*. Classifying is a
// read-only judgement about a sentence — it stores nothing and needs no business scope, and the
// business_id that actually matters is stamped by Java from the JWT when the plan is created.
const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

// Routes one chat turn: is this asking for one post, or a campaign across a date range?
//
// `today` is required upstream and must be the USER's date — the browser's own local date is
// exactly that, and is the reason this is worth proxying rather than letting the server guess.
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));

  if (!body?.message?.trim()) {
    return Response.json({ error: "message is required" }, { status: 400 });
  }
  if (!body?.today) {
    return Response.json({ error: "today is required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${LLM_URL}/intake/classify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json().catch(() => ({}));
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
