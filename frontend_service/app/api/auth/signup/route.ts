import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();

  // See the login proxy: forwarded so Java can refuse to create a second account under an
  // existing session.
  const authHeader = request.headers.get("Authorization");

  try {
    const upstream = await fetch(`${BACKEND_URL}/signIn`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
    });

    const text = await upstream.text();

    if (!upstream.ok) {
      // The 409 guard answers in JSON; every other Java error on this route is a plain string.
      try {
        const parsed = JSON.parse(text);
        if (parsed?.error) return Response.json({ error: parsed.error }, { status: upstream.status });
      } catch {
        // Not JSON — fall through and pass the text along as-is.
      }
      return Response.json({ error: text }, { status: upstream.status });
    }

    return Response.json({ message: text });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
