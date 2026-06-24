import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const body = await request.json();

  try {
    const upstream = await fetch(`${BACKEND_URL}/signIn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const text = await upstream.text();

    if (!upstream.ok) {
      return Response.json({ error: text }, { status: upstream.status });
    }

    return Response.json({ message: text });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
