# Brand Video Storyboard — dynamic composition skill

Supersedes `brand_video.md`'s fixed 3-scene spec. The `media_producer` hands this
file to the LLM (`generate_video_storyboard`), which returns DATA only (no visual
code) matching `core.video_schema.StoryboardSpec`. Rendering the actual MP4
(Remotion + headless Chromium) is intentionally **external** to this service; edit
this file to retune the spec without touching code.

## You are composing, not filling in a template

You do not pick between two fixed video formats. You compose a **storyboard**: an
ordered list of 2-8 `slides`, each one a typed building block from the registry
below. Choose which slide types to use, how many, and in what order, based on what
best tells this brand's story — a stat-heavy launch might lean on `counter_stat` and
`collage`; a simple announcement might be just `hook` → `outro`.

You may **only** use the slide types defined here — the JSON Schema you're given
enumerates them via the `type` discriminator. Never invent a new slide type.

## The slide registry

- **`hook`** — the scroll-stopping opening line, optionally with a cut-out image on
  a geometric shape behind it. Almost always the first slide.
- **`counter_stat`** — 1-4 stat/feature cards (a number or claim + label + icon).
  Use when the brief has concrete numbers or proof points worth dwelling on.
- **`collage`** — 1-4 images arranged on geometric shapes, with an optional header.
  Use for visual storytelling (product, team, lifestyle) rather than numbers.
- **`outro`** — brand name, call-to-action button, optional contact handle.
  Always the last slide.

## Ordering conventions

- Start with `hook` (it's the reason someone keeps watching).
- End with `outro` (it's the only slide with a CTA).
- Put `collage`/`counter_stat` slides in the middle, in whatever order best builds
  the argument — lead with the more visually striking one if both are present.

## Image fields are search keywords, never URLs

`hook.imageQuery` and `collage.imageQueries` are 2-4 word stock-photo search terms
(e.g. `"team meeting laptop"`, `"running shoes city"`) — never a URL, file name, or
description longer than a few words. A later step resolves these to real cut-out
images; you only choose what to search for. Omit `imageQuery`/leave it null for a
text-only hook slide if no image fits.

## Colour palette rules

- `primaryColor`: very dark (near black) — sets the background mood, e.g. `#0d1117`,
  `#1a0a0f`.
- `secondaryColor`: the dominant brand colour — card borders, button gradient start.
- `accentColor`: a complementary pop — shapes, button gradient end.
- All three must contrast strongly against each other and against white text. Derive
  them from the brand's industry, personality, and any colours mentioned in the brief.

## Copy rules

- `brandName`: 1-2 words, ALL CAPS.
- `hook.headline`: 3-7 words, the scroll-stopping opening line.
- `counter_stat.stats`: each item has a short `value`, a `label`, and a single-symbol
  `icon` (e.g. ★ ◆ ▲ ● ■ ✦).
- `outro.ctaLabel`: action verb + 1-2 nouns, e.g. "Start Free Trial", "Book a Demo".
- `outro.contact`: `@handle · domain.com` format, optional.

## Duration

You may suggest a `durationFrames` per slide (at 30fps) if a moment clearly needs
more or less time, but it's optional — when omitted, a sensible per-type default is
used. Don't try to compute exact totals; the platform's typical short-form length
(roughly 15-35 seconds total) is enforced downstream regardless of what you suggest.

Return only valid structured data — no explanation.
