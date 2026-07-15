// Triggers one Remotion Lambda render and polls it to completion. Triggered by
// LLM_service/workflow/video/lambda_render.py — never run standalone in normal
// operation. Prints EXACTLY one JSON line to stdout:
//   success: {"status":"done","url":"https://<bucket>.s3.../output.mp4"}
//   failure: {"status":"error","message":"..."}  (also exits 1)
//
// UNVERIFIED against a live AWS account: no AWS credentials were available in the
// session this was written. The call shapes below ARE confirmed against the
// installed @remotion/lambda-client package's own TypeScript declarations
// (node_modules/@remotion/lambda-client/dist/cjs/{render-media-on-lambda,
// get-render-progress}.d.ts) — this is not a guess at the API, just not yet
// exercised against real AWS infrastructure. Confirm with one real render before
// trusting it in production (see the implementation plan's Phase 2 verification
// steps).

import { readFileSync } from "node:fs";
import { renderMediaOnLambda, getRenderProgress } from "@remotion/lambda/client";

const POLL_INTERVAL_MS = 2000;

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    args[key] = argv[i + 1];
  }
  return args;
}

async function main() {
  const { serveUrl, compositionId, functionName, propsPath, region, outputBucket } = parseArgs(
    process.argv.slice(2),
  );
  if (!serveUrl || !compositionId || !functionName || !propsPath || !region) {
    throw new Error(
      "--serve-url, --composition-id, --function-name, --props-path, and --region are all required",
    );
  }
  const inputProps = JSON.parse(readFileSync(propsPath, "utf-8"));

  const { renderId, bucketName } = await renderMediaOnLambda({
    region,
    functionName,
    serveUrl,
    composition: compositionId,
    inputProps,
    codec: "h264",
    ...(outputBucket ? { forceBucketName: outputBucket } : {}),
  });

  // Polling lives inside this one process/invocation (rather than Python calling
  // back in repeatedly) so the Python side stays a single subprocess call with a
  // single parsed result, matching every other render-adjacent seam in this
  // codebase (render.py/codegen.py's subprocess calls are each one shot too).
  for (;;) {
    const progress = await getRenderProgress({ renderId, bucketName, functionName, region });
    if (progress.fatalErrorEncountered) {
      const messages = (progress.errors || []).map((e) => e.message).join("; ");
      throw new Error(messages || "render failed with no error detail");
    }
    if (progress.done) {
      if (!progress.outputFile) {
        throw new Error("render finished but reported no outputFile");
      }
      console.log(JSON.stringify({ status: "done", url: progress.outputFile }));
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

main().catch((err) => {
  console.log(JSON.stringify({ status: "error", message: String((err && err.message) || err) }));
  process.exit(1);
});
