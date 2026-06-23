import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function POST(request: NextRequest) {
  const { email, password } = await request.json();

  if (!email || !password) {
    return Response.json({ error: "Email and password are required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(
      `${BACKEND_URL}/verifyLogin?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`
    );

    const text = await upstream.text();

    if (text === "Access Granted") {
      return Response.json({ success: true });
    }

    return Response.json({ error: "Invalid email or password" }, { status: 401 });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
