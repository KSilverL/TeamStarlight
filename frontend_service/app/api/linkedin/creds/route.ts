import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Saves the LinkedIn Developer app's client id/secret for the calling business.
// businessId is never sent from here — the Java backend derives it from the
// Authorization header, the same way every other authenticated endpoint does.
export async function POST(request: NextRequest) {
  const body = await request.json();
  const authHeader = request.headers.get("Authorization");

  if (!body.clientId || !body.clientSecret) {
    return Response.json({ error: "clientId and clientSecret are required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/linkedin/addCompCreds`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({ clientId: body.clientId, clientSecret: body.clientSecret }),
    });

    if (!upstream.ok) {
      // The Java endpoint returns a plain-text body on success, not JSON — only read
      // it as text, and only for the error case.
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: text || "Failed to save LinkedIn credentials" },
        { status: upstream.status }
      );
    }

    return Response.json({ success: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
