import { NextRequest } from "next/server";
import { decodeBusinessId } from "@/app/api/_lib/jwt";
import { redirectTo } from "@/app/api/_lib/redirect";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Kicks off the Meta (Facebook) OAuth connect flow. Like the LinkedIn connect route this must
// be reached via a top-level browser navigation (window.location.href = "/api/meta/connect?
// token=..."), not fetch() — the point is to hand the browser a real redirect to Facebook's
// consent screen, which fetch() would follow internally and swallow.
//
// A top-level navigation can't carry an Authorization header, so the JWT rides in the query
// string; from here it's a normal server-to-server call. The Java /meta/auth endpoint takes a
// raw Long businessId in its body (not the header), so we decode it from the token first.
export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("token");
  if (!token) {
    return redirectTo("/login");
  }

  const businessId = decodeBusinessId(`Bearer ${token}`);
  if (businessId === null) {
    return redirectTo("/profile?meta=error");
  }

  // ?force=1 makes Java re-run Facebook's consent screen even when a live token is stored —
  // the Brand Profile sets it because clicking "Connect/Reconnect Facebook" is an explicit
  // request for the dialog (typically to grant a Page the existing token doesn't cover).
  const force = request.nextUrl.searchParams.get("force") === "1";

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/meta/auth?force=${force}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(businessId),
      redirect: "manual",
    });

    // Java always redirects on success — to Facebook's consent screen on a first connect or an
    // expired token, or straight back to the frontend when the stored token is still live.
    const location = upstream.headers.get("location");
    if (location) {
      return Response.redirect(location, 302);
    }

    return redirectTo("/profile?meta=error");
  } catch {
    return redirectTo("/profile?meta=error");
  }
}
