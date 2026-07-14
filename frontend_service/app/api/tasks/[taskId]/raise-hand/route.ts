import { NextRequest } from "next/server";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;
  const body = await request.json();

  if (!body.table_id || typeof body.table_id !== "string") {
    return Response.json({ error: "table_id is required" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${LLM_URL}/tasks/${taskId}/raise-hand`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
