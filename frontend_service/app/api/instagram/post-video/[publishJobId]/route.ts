import { NextRequest } from "next/server";
import { extractJavaError } from "@/app/api/_lib/upstream";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Status of an Instagram publish started by POST /api/instagram/post-video. Instagram transcodes
// asynchronously, so the publish is a job the client polls rather than one long request.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ publishJobId: string }> }
) {
  const { publishJobId } = await params;
  // Forwarded, not trusted: the backend only reports on jobs belonging to the business in
  // this token, so one business cannot poll another's publish.
  const authHeader = request.headers.get("Authorization");

  try {
    const upstream = await fetch(
      `${JAVA_SERVICE_URL}/instagram/post-video/${encodeURIComponent(publishJobId)}`,
      {
        headers: { ...(authHeader ? { Authorization: authHeader } : {}) },
        cache: "no-store",
      }
    );

    const text = await upstream.text().catch(() => "");
    if (!upstream.ok) {
      return Response.json(
        { error: extractJavaError(text) || "Could not read the Instagram publish status" },
        { status: upstream.status }
      );
    }
    // Success bodies carry status/stage/mediaIds, which the poller reads field by field.
    try {
      return Response.json(JSON.parse(text), { status: upstream.status });
    } catch {
      return Response.json(
        { error: "Malformed Instagram publish status from the backend" },
        { status: 502 }
      );
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Instagram backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
