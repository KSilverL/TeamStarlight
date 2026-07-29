import { NextRequest } from "next/server";
import { decodeBusinessId } from "@/app/api/_lib/jwt";
import { extractJavaError } from "@/app/api/_lib/upstream";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Publishes a text or image post to one or more connected Facebook Pages via Java's
// /meta/post (@ModelAttribute CrossPlatPostReqDTO — multipart). The browser sends `message`,
// an optional `image` File, and one repeated `pageId` field per selected Page. We inject
// `businessId` from the JWT and rename `image` → `media` (the DTO's field name). A missing
// media field makes Java post to /{page_id}/feed (text-only); an image makes it /photos.
export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");

  const businessId = decodeBusinessId(authHeader);
  if (businessId === null) {
    return Response.json({ error: "You need to be logged in to post to Facebook." }, { status: 401 });
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  const message = form.get("message");
  const pageIds = form.getAll("pageId").map((v) => String(v)).filter((v) => v.trim() !== "");
  const image = form.get("image");

  if (typeof message !== "string" || message.trim() === "") {
    return Response.json({ error: "message is required" }, { status: 400 });
  }
  if (pageIds.length === 0) {
    return Response.json(
      { error: "Select a Facebook Page in your Brand Profile first." },
      { status: 400 }
    );
  }

  try {
    const upstreamForm = new FormData();
    upstreamForm.append("businessId", String(businessId));
    upstreamForm.append("message", message);
    for (const id of pageIds) upstreamForm.append("pageId", id);
    if (image instanceof File && image.size > 0) {
      upstreamForm.append("media", image, image.name || "image");
    }

    // No Content-Type header — fetch sets the multipart boundary from the FormData.
    const upstream = await fetch(`${JAVA_SERVICE_URL}/meta/post`, {
      method: "POST",
      body: upstreamForm,
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: extractJavaError(text) || "Failed to post to Facebook" },
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
