# Brand Animation — animated HTML card skill

The style guide for the **post-approval animated HTML card** (the "生成 HTML" idea,
ported from `demos/brand_agent`). The `media_producer` hands this file to the LLM
(`render_html_card`) verbatim; edit it to retune the look without touching code. It
replaces the old static platform preview card.

## Output contract
- Output a **SINGLE, COMPLETE, SELF-CONTAINED HTML document** — nothing else. No markdown
  fences, no explanation. Start with `<!DOCTYPE html>` and end with `</html>`.
- All CSS, JS and SVG **inline** — no external images, fonts, or CDN links. It must render
  in any modern browser with no network.
- Never inject the raw post copy as markup — treat it as text content.

## Visual style
- A **9:16 portrait "video card"** (360×640 viewport) with **3 animated scenes** that
  auto-advance every ~4 seconds, with dot/prev-next controls.
  - Scene 1 — brand identity: logo mark / initial, brand name, tagline, mood.
  - Scene 2 — the heart of the approved post (key message / highlights) with staggered
    entrance animations.
  - Scene 3 — call-to-action with a prominent button and a closing line.
- CSS keyframe animations for every element (`fadeIn`, `riseUp`, `pulse`, `drawLine`, …);
  each text element animates in with a stagger delay.
- Derive a coherent palette of 3–5 colours from the brand topic and use it throughout.
- Typography: `Georgia, serif` for display text, `system-ui, sans-serif` for labels/CTAs.
- Responsive stage: `max-width:360px; aspect-ratio:9/16; margin:0 auto`.

Make the animation rich and on-brand — use shapes and visual metaphors tied to the brand's
product or industry.
