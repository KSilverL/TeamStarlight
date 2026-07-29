// Browser redirect out of an API route, addressed relative to whatever host the browser used.
//
// Do NOT build these with `new URL(path, request.url)`: in a Next.js standalone build (what the
// Docker image runs) request.url is assembled from the HOSTNAME env var, which the server sets
// to 0.0.0.0 so it binds every interface. The redirect then points at http://0.0.0.0:3000/...,
// a bind address the browser cannot navigate to (ERR_ADDRESS_INVALID).
//
// A relative Location header is valid per RFC 7231 and every browser resolves it against the
// origin it actually requested — so this works identically on localhost, in Docker, and behind
// a reverse proxy, with no env var to keep in sync.
export function redirectTo(path: string) {
  return new Response(null, { status: 302, headers: { Location: path } });
}
