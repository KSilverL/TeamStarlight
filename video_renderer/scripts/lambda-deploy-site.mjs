// Deploys an ephemeral Remotion Lambda "site" (a bundled build of this project)
// for one render job that needs its own bespoke `generated` component(s) baked in.
// Triggered by LLM_service/workflow/video/lambda_render.py — never run standalone
// in normal operation. Prints EXACTLY one JSON line to stdout:
//   success: {"status":"done","serveUrl":"https://..."}
//   failure: {"status":"error","message":"..."}  (also exits 1)
//
// UNVERIFIED against a live AWS account: no AWS credentials were available in the
// session this was written. The call shapes below ARE confirmed against the
// installed @remotion/lambda package's own TypeScript declarations
// (node_modules/@remotion/lambda/dist/api/deploy-site.d.ts and
// get-or-create-bucket.d.ts) — this is not a guess at the API, just not yet
// exercised against real AWS infrastructure. Confirm with one real deploy before
// trusting it in production (see the implementation plan's Phase 2 verification
// steps).

import { deploySite, getOrCreateBucket } from "@remotion/lambda";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    args[key] = argv[i + 1];
  }
  return args;
}

async function main() {
  const { entryPoint, siteName, region } = parseArgs(process.argv.slice(2));
  if (!entryPoint || !siteName || !region) {
    throw new Error("--entry-point, --site-name, and --region are all required");
  }

  // One "Remotion bucket" per region hosts every site + render output — created
  // once, reused after (getOrCreateBucket is idempotent: `alreadyExisted` tells
  // you which happened, but either way you get a usable bucketName back).
  const { bucketName } = await getOrCreateBucket({ region });
  const { serveUrl } = await deploySite({ entryPoint, siteName, bucketName, region });

  console.log(JSON.stringify({ status: "done", serveUrl }));
}

main().catch((err) => {
  console.log(JSON.stringify({ status: "error", message: String((err && err.message) || err) }));
  process.exit(1);
});
