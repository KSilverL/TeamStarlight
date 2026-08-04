import { NextRequest } from "next/server";
import { extractJavaError } from "@/app/api/_lib/upstream";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// The content calendar's list/create endpoint, proxying Java's /schedule/posts.
//
// The Authorization header is passed straight through and Java derives the business from it —
// nothing here decodes or supplies a businessId, so a caller can only ever see its own schedule.

export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return Response.json(
      { error: "You need to be logged in to see your calendar." },
      { status: 401 }
    );
  }

  const { searchParams } = new URL(request.url);
  const query = new URLSearchParams();
  for (const key of ["from", "to", "timezone"]) {
    const value = searchParams.get(key);
    if (value) query.set(key, value);
  }

  try {
    const upstream = await fetch(
      `${JAVA_SERVICE_URL}/schedule/posts?${query.toString()}`,
      { headers: { Authorization: authHeader } }
    );

    const text = await upstream.text();
    if (!upstream.ok) {
      return Response.json(
        { error: extractJavaError(text) || "Could not load your scheduled posts." },
        { status: upstream.status }
      );
    }
    return Response.json(JSON.parse(text), { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return Response.json(
      { error: "You need to be logged in to schedule a post." },
      { status: 401 }
    );
  }

  const body = await request.json().catch(() => ({}));
  const { platform, message, date, time, scheduled_time, timezone, hashtags, page_ids } = body;

  if (!platform || typeof platform !== "string") {
    return Response.json({ error: "platform is required" }, { status: 400 });
  }
  if (!message || typeof message !== "string" || !message.trim()) {
    return Response.json({ error: "message is required" }, { status: 400 });
  }

  // The calendar holds the day and the time as separate controls, so accept them that way and
  // compose here. Java takes one wall-clock string plus the zone it was picked in, which is what
  // keeps a 09:00 post at 09:00 rather than drifting by the server's UTC offset.
  const scheduledTime =
    typeof scheduled_time === "string" && scheduled_time
      ? scheduled_time
      : date && time
        ? `${date}T${time}:00`
        : null;

  if (!scheduledTime) {
    return Response.json(
      { error: "Provide either scheduled_time, or both date and time." },
      { status: 400 }
    );
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/schedule/posts`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: authHeader,
      },
      body: JSON.stringify({
        platform,
        message,
        scheduled_time: scheduledTime,
        // The zone has to come from the browser — resolving it here would read the *server's*
        // zone, which is the same mistake (ZoneId.systemDefault() on a UTC container) that made
        // posts fire an hour off. Omitted means Java falls back to its configured app.timezone.
        ...(typeof timezone === "string" && timezone ? { timezone } : {}),
        hashtags: Array.isArray(hashtags) ? hashtags : [],
        page_ids: Array.isArray(page_ids) ? page_ids.map(Number).filter(Number.isFinite) : [],
      }),
    });

    const text = await upstream.text();
    if (!upstream.ok) {
      return Response.json(
        { error: extractJavaError(text) || "Failed to schedule the post." },
        { status: upstream.status }
      );
    }
    return Response.json(JSON.parse(text), { status: upstream.status });
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: errorMessage }, { status: 502 });
  }
}
