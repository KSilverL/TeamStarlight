import { NextRequest } from "next/server";
import { extractJavaError } from "@/app/api/_lib/upstream";

// BACKEND_URL is what docker-compose actually sets for this service; the previous
// JAVA_BACKEND_URL was never defined anywhere and silently fell through to its default.
const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Starts publishing a finished video render job to Instagram as a Reel. Returns 202 with a
// publishJobId to poll at GET /api/instagram/post-video/[publishJobId] — Instagram transcodes
// asynchronously and can take minutes, far longer than a browser will hold a request open.
// Credential and permission errors are still reported synchronously in this response.
export async function POST(request: NextRequest) {
  const body = await request.json();
  // Forwarded, not trusted: the backend derives the business from this token and ignores
  // anything the body claims, so a caller cannot publish through another business's account.
  const authHeader = request.headers.get("Authorization");

  if (!body.jobId || typeof body.jobId !== "string") {
    return Response.json({ error: "jobId is required" }, { status: 400 });
  }
  if (!Array.isArray(body.pageIds) || body.pageIds.length === 0) {
    return Response.json(
      {
        error:
          "Connect Facebook and pick a Page in your Brand Profile first — an Instagram post is published through the Page its account is linked to.",
      },
      { status: 400 }
    );
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/instagram/post-video`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify({
        jobId: body.jobId,
        caption: typeof body.caption === "string" ? body.caption : "",
        pageIds: body.pageIds,
      }),
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      // The backend reports credential and Graph failures as {"error": "..."} naming the fix;
      // relay that rather than flattening it to a generic message.
      return Response.json(
        { error: extractJavaError(text) || "Failed to post video to Instagram" },
        { status: upstream.status }
      );
    }

    const data = await upstream.json();
    return Response.json(data, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Instagram backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
