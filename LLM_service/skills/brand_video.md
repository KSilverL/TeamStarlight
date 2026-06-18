# Brand Video — structured props skill

The spec for the **post-approval video props** (the "生成视频" idea, ported from
`demos/brand_video_agent`). The `media_producer` hands this file to the LLM
(`generate_video_props`), which returns DATA only (no visual code) matching
`core.media_schema.BrandVideoProps`. Rendering the actual MP4 (Remotion + headless
Chromium) is intentionally **external** to this service; edit this file to retune the
spec without touching code.

Describe a **12-second, 3-scene portrait video** (9:16, 1080×1920):
- Scene 1 — brand identity: name, tagline, mood.
- Scene 2 — three key stats or product highlights.
- Scene 3 — call-to-action with headline, subtext, button label, contact.

## Colour palette rules
- `primaryColor`: very dark (near black) — sets the background mood, e.g. `#0d1117`, `#1a0a0f`.
- `secondaryColor`: the dominant brand colour — logo, card borders, button gradient start.
- `accentColor`: a complementary pop — lines, dots, button gradient end.
- All three must contrast strongly against each other and against white text. Derive them
  from the brand's industry, personality, and any colours mentioned in the brief.

## Copy rules
- `brandName`: 1–2 words, ALL CAPS.
- `tagline`: 3–6 words, no punctuation.
- `sectionLabel`: a short Scene-2 header, e.g. "Why Choose Us".
- `stats`: **exactly 3** items — mix numeric stats with a quality claim; each has a short
  `value`, a `label`, and a single-symbol `icon` (e.g. ★ ◆ ▲ ● ■ ✦).
- `headline`: 3–5 words, ends with `?`.
- `subtext`: one sentence, max 12 words.
- `ctaLabel`: action verb + 1–2 nouns, e.g. "Start Free Trial", "Book a Demo".
- `contact`: `@handle · domain.com` format.

Return only valid structured data — no explanation.
