import { NextRequest } from "next/server";
import { decodeBusinessId } from "@/app/api/_lib/jwt";
import { extractJavaError } from "@/app/api/_lib/upstream";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";
const LLM_URL = process.env.LLM_SERVICE_URL ?? "http://localhost:8080";

// Publishes a rendered storyboard video to one or more Facebook Pages. The browser passes the
// render `jobId` (not the bytes); we fetch the finished MP4 from the LLM service server-side
// and re-upload it to Java's /meta/post as the `media` file, keeping the large transfer off
// the browser — the same division of labour the LinkedIn video post uses.
export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");
  const body = await request.json().catch(() => ({}));

  const businessId = decodeBusinessId(authHeader);
  if (businessId === null) {
    return Response.json({ error: "You need to be logged in to post to Facebook." }, { status: 401 });
  }

  const jobId: string = typeof body.jobId === "string" ? body.jobId : "";
  const message: string = typeof body.message === "string" ? body.message : "";
  const title: string = typeof body.title === "string" ? body.title : "";
  const description: string = typeof body.description === "string" ? body.description : "";
  const pageIds: string[] = Array.isArray(body.pageIds)
    ? body.pageIds.map((v: unknown) => String(v)).filter((v: string) => v.trim() !== "")
    : [];

  if (!jobId.trim()) {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }
  if (!message.trim()) {
    return Response.json({ error: "message is required" }, { status: 400 });
  }
  if (pageIds.length === 0) {
    return Response.json(
      { error: "Select a Facebook Page in your Brand Profile first." },
      { status: 400 }
    );
  }

  try {
    const videoRes = await fetch(`${LLM_URL}/video-jobs/${jobId}/download`);
    if (!videoRes.ok) {
      return Response.json(
        { error: `Could not fetch the rendered video for job ${jobId}.` },
        { status: 502 }
      );
    }
    const videoBlob = await videoRes.blob();

    const upstreamForm = new FormData();
    upstreamForm.append("businessId", String(businessId));
    upstreamForm.append("message", message);
    upstreamForm.append("title", title);
    upstreamForm.append("description", description);
    for (const id of pageIds) upstreamForm.append("pageId", id);
    upstreamForm.append("media", videoBlob, `${jobId}.mp4`);

    const upstream = await fetch(`${JAVA_SERVICE_URL}/meta/post`, {
      method: "POST",
      body: upstreamForm,
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: extractJavaError(text) || "Failed to post video to Facebook" },
        { status: upstream.status }
      );
    }

    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
