import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const authHeader = request.headers.get("Authorization");
  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/api/sessions/${id}/messages`, {
      headers: { ...(authHeader ? { Authorization: authHeader } : {}) },
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch {
    return Response.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
