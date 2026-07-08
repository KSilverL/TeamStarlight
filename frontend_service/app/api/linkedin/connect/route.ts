import { NextRequest } from "next/server";

const JAVA_SERVICE_URL = process.env.BACKEND_URL ?? "http://localhost:8081";

// Kicks off the LinkedIn OAuth connect flow. This route must be reached via a
// top-level browser navigation (window.location.href = "/api/linkedin/connect?token=..."),
// not fetch() — the whole point is to hand the browser a real redirect to LinkedIn's
// consent screen, which fetch() would otherwise just follow internally and swallow.
//
// A top-level navigation can't carry a custom Authorization header, so the button that
// triggers this embeds the JWT in the query string instead; from here on it's a normal
// Authorization header for the server-to-server call to the Java backend, which derives
// businessId from it (never from a client-supplied value).
export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("token");
  if (!token) {
    return Response.redirect(new URL("/login", request.url), 302);
  }

  try {
    const upstream = await fetch(`${JAVA_SERVICE_URL}/linkedin/auth`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      redirect: "manual",
    });

    // Java always redirects on success — either to LinkedIn's consent screen (first
    // connect / expired token) or straight back to the frontend (already connected).
    const location = upstream.headers.get("location");
    if (location) {
      return Response.redirect(location, 302);
    }

    return Response.redirect(new URL("/profile?linkedin=error", request.url), 302);
  } catch {
    return Response.redirect(new URL("/profile?linkedin=error", request.url), 302);
  }
}
