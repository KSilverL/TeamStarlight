import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const { email, password } = await request.json();

  if (!email || !password) {
    return Response.json({ error: "Email and password are required" }, { status: 400 });
  }

  // Forwarded so Java can refuse a login from someone who already holds a session (409). Not
  // checked here: verifying the signature needs the secret, which only Java has.
  const authHeader = request.headers.get("Authorization");

  try {
    const upstream = await fetch(`${BACKEND_URL}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({ email, password }),
    });

    const data = await upstream.json();

    if (!upstream.ok) {
      return Response.json({ error: data.error ?? "Invalid email or password" }, { status: upstream.status });
    }

    return Response.json({ token: data.token });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
