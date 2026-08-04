import { NextRequest } from "next/server";
import { extractJavaError } from "@/app/api/_lib/upstream";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Read / reschedule / cancel one scheduled post. Java scopes each of these to the business in
// the token, so an id belonging to someone else comes back as a 404 rather than acting on it.

type Params = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return Response.json({ error: "You need to be logged in." }, { status: 401 });
  }

  return relay(`${JAVA_SERVICE_URL}/schedule/posts/${id}`, {
    headers: { Authorization: authHeader },
  }, "Could not load that scheduled post.");
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return Response.json({ error: "You need to be logged in." }, { status: 401 });
  }

  const body = await request.json().catch(() => ({}));
  const { date, time, scheduled_time, timezone, message, hashtags, page_ids } = body;

  // Same date+time composition as the create route — the calendar edits the two separately.
  const scheduledTime =
    typeof scheduled_time === "string" && scheduled_time
      ? scheduled_time
      : date && time
        ? `${date}T${time}:00`
        : undefined;

  return relay(`${JAVA_SERVICE_URL}/schedule/posts/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: authHeader,
    },
    // Only forward what the caller actually set: Java treats a null field as "leave alone",
    // so sending the whole shape would blank out everything the user didn't touch.
    body: JSON.stringify({
      ...(scheduledTime ? { scheduled_time: scheduledTime } : {}),
      ...(typeof timezone === "string" && timezone ? { timezone } : {}),
      ...(typeof message === "string" ? { message } : {}),
      ...(Array.isArray(hashtags) ? { hashtags } : {}),
      ...(Array.isArray(page_ids)
        ? { page_ids: page_ids.map(Number).filter(Number.isFinite) }
        : {}),
    }),
  }, "Failed to update the scheduled post.");
}

export async function DELETE(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return Response.json({ error: "You need to be logged in." }, { status: 401 });
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/schedule/posts/${id}`, {
      method: "DELETE",
      headers: { Authorization: authHeader },
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: extractJavaError(text) || "Failed to cancel the scheduled post." },
        { status: upstream.status }
      );
    }
    // Java answers 204; a Response.json body would contradict that status.
    return new Response(null, { status: 204 });
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: errorMessage }, { status: 502 });
  }
}

/** Forwards to Java and relays its JSON, turning a Spring error envelope into a plain
 * { error } the calendar can show without unwrapping it itself. */
async function relay(url: string, init: RequestInit, fallbackError: string) {
  try {
    const upstream = await fetch(url, init);
    const text = await upstream.text();

    if (!upstream.ok) {
      return Response.json(
        { error: extractJavaError(text) || fallbackError },
        { status: upstream.status }
      );
    }
    return Response.json(text ? JSON.parse(text) : {}, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
