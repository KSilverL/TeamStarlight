import { NextRequest } from "next/server";

const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> }
) {
  const { taskId } = await params;

  try {
    const upstream = await fetch(`${LLM_URL}/tasks/${taskId}`);
    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "LLM service unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
