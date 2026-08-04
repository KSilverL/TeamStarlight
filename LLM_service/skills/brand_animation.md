# Brand Animation — animated HTML card skill

The style guide for the **post-approval animated HTML card** (the "generate HTML" idea,
ported from `demos/brand_agent`). The `media_producer` hands this file to the LLM
(`render_html_card`) verbatim; edit it to retune the look without touching code. It
replaces the old static platform preview card.

## Output contract
- Output a **SINGLE, COMPLETE, SELF-CONTAINED HTML document** — nothing else. No markdown
  fences, no prose, no explanation. Start with `<!DOCTYPE html>` and end with `</html>`.
- All CSS, JS and SVG **inline** — no external images, fonts, or CDN links. It must render
  in any modern browser with no network access.
- Never inject the raw post copy as markup — treat it as text content (escape it), so a
  stray `<` or `&` in the copy can't break the layout.
- No layout that depends on JS to appear: the card must look right even if scripts are off
  (JS may enhance the scene controls, but CSS drives the reveal).

## Visual style
- A **9:16 portrait "video card"** (360×640 viewport) with **3 animated scenes** that
  auto-advance every ~4 seconds, with dot / prev-next controls.
  - Scene 1 — brand identity: logo mark / initial, brand name, tagline, mood.
  - Scene 2 — the heart of the approved post (key message / highlights) with staggered
    entrance animations.
  - Scene 3 — call-to-action with a prominent button and a closing line.
- Responsive stage: `max-width:360px; aspect-ratio:9/16; margin:0 auto` — never a fixed
  pixel height that clips on small screens.

## Motion & timing
- Every element enters with a CSS keyframe animation (`fadeIn`, `riseUp`, `pulse`,
  `drawLine`, `slideUp`, …); text elements **stagger** in (each ~80–150 ms after the last)
  so a scene assembles rather than snapping.
- Keep entrances quick (300–800 ms) and easing natural (`ease`, `ease-out`, `cubic-bezier`).
  Reserve looping animation (`pulse`, subtle float) for the CTA only — motion everywhere
  reads as noise.
- Scenes cross-fade; nothing should hard-cut. Total loop ≈ 12 s (3 scenes × ~4 s).
- Honour `@media (prefers-reduced-motion: reduce)` — collapse animations to a simple fade
  for viewers who ask for less motion.

## Palette & typography
- Derive a coherent palette of **3–5 colours** from the brand topic/industry (a primary, a
  secondary, an accent, plus neutrals) and use it consistently across all three scenes —
  don't restyle per scene.
- Typography: `Georgia, serif` for display text, `system-ui, sans-serif` for labels / CTAs.
  Establish a clear hierarchy (one large display line, supporting text noticeably smaller).

## Accessibility & legibility
- Maintain strong text/background contrast (aim for WCAG AA on body text) — light text on a
  dark stage, or vice versa, never mid-tone on mid-tone.
- Text must never touch the canvas edge; keep generous padding (≥ 24 px) and don't let a
  long headline or the post body overflow — wrap or scale it down.

## Craft
- Make the animation rich and on-brand: use shapes, SVG marks, and visual metaphors tied to
  the brand's product or industry — not generic boxes.

## Avoid
- External assets, `<img src="http…">`, web fonts, tracking scripts, or anything that hits
  the network.
- Unescaped post copy in markup, mid-tone-on-mid-tone text, a fixed height that clips, or
  constant full-card motion that fights the message.

## Self-check before returning
- Is it one self-contained document, `<!DOCTYPE html>` → `</html>`, with zero network calls?
- Do all three scenes share one palette, stay legible, and stagger their entrances?
- Is the post copy escaped, padded off the edges, and fully visible without overflow?
