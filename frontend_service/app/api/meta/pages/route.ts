import { NextRequest } from "next/server";
import { decodeBusinessId } from "@/app/api/_lib/jwt";
import { extractJavaError } from "@/app/api/_lib/upstream";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Fetches the Facebook Pages the connected Meta account manages, so the user can pick which
// Page(s) approved drafts should publish to. Java's /meta/addPageInfo re-reads the pages from
// the Graph API, stores them, and returns { pageIds, pageNames }. It needs a live access token
// (i.e. the business must have completed the OAuth connect first) or the upstream call fails.
export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("Authorization");

  const businessId = decodeBusinessId(authHeader);
  if (businessId === null) {
    return Response.json({ error: "You need to be logged in to load Facebook Pages." }, { status: 401 });
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/meta/addPageInfo`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(businessId),
    });

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: extractJavaError(text) || "Could not load Facebook Pages — connect Facebook first." },
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
