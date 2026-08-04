import { NextRequest, NextResponse } from "next/server";
import { extractJavaError } from "@/app/api/_lib/upstream";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Schedules the approved copy for one plan slot.
//
// Called immediately after a successful approve: the LLM service keeps task outputs in memory,
// so the copy has to be captured into the database while it is still there. Java answers 200
// with a per-platform breakdown even when nothing could be scheduled, so the caller must read
// the body rather than trusting the status alone.
export async function POST(
  req: NextRequest,
  context: { params: Promise<{ planId: string; itemId: string }> }
) {
  const { planId, itemId } = await context.params;
  const authHeader = req.headers.get("Authorization");

  if (!authHeader) {
    return NextResponse.json(
      { error: "You need to be logged in to schedule a post." },
      { status: 401 }
    );
  }

  const body = await req.json().catch(() => ({}));
  // The browser knows which Facebook Pages the user picked (Brand Profile keeps the selection
  // in localStorage). Java falls back to every Page on the connection when this is absent.
  const pageIds = Array.isArray(body?.page_ids)
    ? body.page_ids.map(Number).filter(Number.isFinite)
    : [];

  try {
    const upstream = await fetch(
      `${BACKEND_URL}/plans/${planId}/items/${itemId}/schedule`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: authHeader,
        },
        body: JSON.stringify({ page_ids: pageIds }),
      }
    );

    const text = await upstream.text();
    if (!upstream.ok) {
      return NextResponse.json(
        { error: extractJavaError(text) || "Could not schedule this slot." },
        { status: upstream.status }
      );
    }
    return NextResponse.json(text ? JSON.parse(text) : {}, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
