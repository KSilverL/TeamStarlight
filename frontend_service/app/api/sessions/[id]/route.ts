import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Names a session. Goes through Java rather than the LLM service because Java owns the
// sessions table — and because it derives the caller's business from the JWT to check they
// own the session they're renaming.
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const authHeader = request.headers.get("Authorization");
  const body = await request.json().catch(() => ({}));
  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/api/sessions/${id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({ title: body.title ?? null }),
    });
    const data = await upstream.json().catch(() => ({}));
    return Response.json(data, { status: upstream.status });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
