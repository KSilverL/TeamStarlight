import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Posts a user-attached image to LinkedIn. Unlike the text/video routes this forwards
// multipart/form-data (the raw image file + a text message) straight through to the Java
// backend — the browser uploads a real file here rather than referencing a rendered asset by
// id. businessId is never sent from here; the Java backend derives it from the JWT.
export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  const image = form.get("image");
  const message = form.get("message");
  if (!(image instanceof File) || image.size === 0) {
    return Response.json({ error: "image file is required" }, { status: 400 });
  }
  if (typeof message !== "string" || message.trim() === "") {
    return Response.json({ error: "message is required" }, { status: 400 });
  }

  try {
    // Re-build the form so only the fields the backend expects are forwarded; passing the raw
    // FormData through lets fetch set the multipart boundary/Content-Type automatically.
    const upstreamForm = new FormData();
    upstreamForm.append("image", image, image.name || "image");
    upstreamForm.append("message", message);

    const upstream = await fetch(`${JAVA_SERVICE_URL}/linkedin/post-image`, {
      method: "POST",
      headers: {
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: upstreamForm,
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: text || "Failed to post image to LinkedIn" },
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
