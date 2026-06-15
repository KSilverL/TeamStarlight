# HTML Designer — platform preview card skill

The spec for the **platform-simulated preview card** (MIGRATION_PLAN §5.4): a small,
self-contained HTML fragment that renders a draft inside a faithful mock of the target
platform's post UI, so the user previews the post *as it will look* — replacing image
generation on the critical path. `core/preview.py` implements this spec deterministically
(no LLM needed offline); a production renderer can hand this file to an LLM for richer cards.

## Output contract
- Return **one self-contained HTML fragment** (a single root `<div class="preview-card …">`
  with an inline `<style scoped>`). No `<html>/<body>`, no external CSS/JS/fonts, no network
  assets — it must drop straight into the frontend and render as-is. This fragment is what the
  SSE `result` event carries in `html_preview`.
- Escape the draft text (`&`, `<`, `>`) — never inject raw user copy into markup.
- Preserve the draft's line breaks (`\n` → `<br>`).

## Platform chrome (simulate the real frame)
- **LinkedIn** — white card, avatar circle + name + "· 1st" + muted timestamp, post body,
  a faint reactions/comment bar footer. Accent `#0a66c2`.
- **Twitter / X** — dark card (`#15202b`), avatar + name + grey `@handle`, body, a row of
  reply/retweet/like glyphs. Accent `#1d9bf0`.
- **Instagram** — square-ish card, gradient avatar ring, username header, a placeholder media
  block, then heart/comment/share row and the caption. Accent gradient
  `#feda75→#d62976→#4f5bd5`.

## Animation
- One subtle, tasteful CSS entrance (e.g. `@keyframes fadeInUp`) on the root card. Keep it
  under ~400ms; no infinite loops, no layout thrash.

## A11y / size
- Keep the whole fragment well under ~6 KB. Use semantic-ish structure and adequate contrast.
