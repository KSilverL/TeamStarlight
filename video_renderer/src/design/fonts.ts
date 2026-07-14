// Brand-video typography as SELF-CONTAINED system font stacks — deliberately NOT
// @remotion/google-fonts. That loader fetches woff2 files from fonts.gstatic.com at
// render time; in a sandboxed/offline/Lambda render (or a flaky network) that fetch
// times out and HARD-FAILS the whole render — the exact reliability regression the
// codegen work in Phase 1 set out to remove. A render must never depend on a live
// network fetch. These stacks always resolve, headless-Chromium included.
//
// displayFont: a geometric/grotesk stack for headlines, brand names, hero numbers.
// bodyFont: a clean humanist-sans stack for labels, legends, captions, table cells.
// To ship the distinctive Sora/Inter look later, self-host their woff2 files under
// public/fonts/ and @font-face them via staticFile() — local files, never a fetch.

/** Display type: headlines, brand names, hero stats. */
export const displayFont =
  '"Segoe UI Variable Display", "Segoe UI", "Avenir Next", "Futura", "Helvetica Neue", Arial, sans-serif';

/** Body type: labels, legends, captions, table cells. */
export const bodyFont =
  '"Segoe UI", "Inter", "Helvetica Neue", Arial, system-ui, sans-serif';
