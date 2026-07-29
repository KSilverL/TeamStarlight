import { NextRequest } from "next/server";
import { decodeBusinessId } from "@/app/api/_lib/jwt";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Saves the Meta (Facebook) Developer app's client id/secret for the calling business.
//
// Unlike LinkedIn, Meta creds live on the shared /global/* endpoints, which key on a
// body-supplied businessId — so we decode it from the JWT here (the browser never sends it).
// /global/addCompCreds always INSERTS, so we first check for an existing META record and
// switch to /global/updateCompCreds when one is present, to avoid piling up duplicate rows.
export async function POST(request: NextRequest) {
  const body = await request.json();
  const authHeader = request.headers.get("Authorization");

  const businessId = decodeBusinessId(authHeader);
  if (businessId === null) {
    return Response.json({ error: "You need to be logged in to connect Facebook." }, { status: 401 });
  }
  if (!body.clientId || !body.clientSecret) {
    return Response.json({ error: "clientId and clientSecret are required" }, { status: 400 });
  }

  const credPayload = [
    {
      businessId,
      clientId: String(body.clientId).trim(),
      clientSecret: String(body.clientSecret).trim(),
      platform: "META",
    },
  ];

  try {
    // Does a META record already exist for this business? If so, update rather than insert.
    let exists = false;
    try {
      const check = await fetch(
        `${JAVA_SERVICE_URL}/global/getCompCreds?businessId=${businessId}&platforms=META`,
        { method: "GET" }
      );
      if (check.ok) {
        const records = await check.json().catch(() => []);
        exists = Array.isArray(records) && records.length > 0;
      }
    } catch {
      // Non-fatal — fall back to insert if the existence check can't be reached.
    }

    const upstream = await fetch(
      `${JAVA_SERVICE_URL}/global/${exists ? "updateCompCreds" : "addCompCreds"}`,
      {
        method: exists ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credPayload),
      }
    );

    if (!upstream.ok) {
      const text = await upstream.text().catch(() => "");
      return Response.json(
        { error: text || "Failed to save Facebook credentials" },
        { status: upstream.status }
      );
    }

    return Response.json({ success: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Backend unreachable";
    return Response.json({ error: message }, { status: 502 });
  }
}
