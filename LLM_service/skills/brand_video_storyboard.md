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
- **`pie_chart`** — 2-6 proportional segments, optionally with a short stat callout.
  Use for "how the whole breaks down" stories (budget split, market share).
- **`line_chart`** — 1-2 trend lines drawn across 2-8 x-axis points (e.g. years).
  Use for "this changed over time" stories. Two series invites comparison.
- **`bar_chart`** — 2-6 bars compared side by side. Use for ranking or comparing a
  handful of discrete things at a single point in time (not a trend).
- **`node_diagram`** — 3-6 short concept labels shown as a connected chain. Use to
  show how one idea leads to another (cause → effect, theme → theme).
- **`comparison_table`** — 1-4 columns × 2-5 rows, revealed one row at a time. Use
  when there are several named things being compared on the same few attributes.
- **`map`** — a country/region map with 1-5 animated location pins, each with a
  `label` and up to 3 short `stats` lines. Use whenever the story is about *places*
  (cities, offices, markets, regional expansion). `region` is the ISO 3166-1
  alpha-2 country code, UPPERCASE (e.g. `"IE"` for Ireland); each pin needs real
  WGS84 coordinates — `lon` (negative = west) and `lat` — e.g. Dublin is
  lon `-6.26`, lat `53.35`. Prefer this over `generated` for ANY map-like request.
- **`outro`** — brand name, call-to-action button, optional contact handle.
  Always the last slide.
- **`generated`** — a BESPOKE scene, authored as real code by a separate agent, for
  when none of the fixed types above genuinely fit. You provide `description` (the
<<<<<<< Updated upstream
  creative brief — HOW to present the scene) and `data`, which MUST carry ALL the
  structured content the scene renders — numbers, labels, series, coordinates — as
  typed JSON values. `description` says how to present what's in `data`; it must
  never be the only carrier of the content itself. Bad: `description: "show
  Dublin's population of 1.2M and Cork's of 0.2M as rising towers"` with `data: {}`.
  Good: the same `description` with `data: {"cities": [{"name": "Dublin", "pop":
  1200000}, {"name": "Cork", "pop": 220000}]}`. This is slower and less predictable
  than a fixed type (it's authored, typechecked, and preview-rendered fresh, with a
  bounded number of retries), so use it sparingly — if a fixed type (including
  `map`) can express it, never use `generated`.
=======
  creative brief — what this scene should show/communicate) and `data` (whatever
  structured content it needs: headline text, numbers, labels — its shape is
  whatever `description` implies, not fixed). This is slower and less predictable
  than a fixed type (it's authored, typechecked, and preview-rendered fresh, with a
  bounded number of retries), so use it sparingly — only when the story genuinely
  needs something the registry can't express, not as a default choice.
>>>>>>> Stashed changes

## Ordering conventions

- Start with `hook` (it's the reason someone keeps watching).
- End with `outro` (it's the only slide with a CTA).
- Put every other slide type in the middle, in whatever order best builds the
  argument — lead with the most visually striking one, and don't feel obligated to
  use every type in one storyboard. Most storyboards should use 1-3 of the
  data/visual middle slide types, not all of them at once.

## Image fields are search keywords, never URLs

`hook.imageQuery` and `collage.imageQueries` are 2-4 word stock-photo search terms
(e.g. `"team meeting laptop"`, `"running shoes city"`) — never a URL, file name, or
description longer than a few words. A later step resolves these to real cut-out
images; you only choose what to search for. Omit `imageQuery`/leave it null for a
text-only hook slide if no image fits.

## Chart/data fields are illustrative, not looked up

There is no live data source behind `pie_chart`, `line_chart`, `bar_chart`,
`node_diagram`, or `comparison_table` — you invent plausible, on-brief numbers and
labels yourself, the same way you already invent `counter_stat.stats`. Keep them
consistent with any real figures mentioned in the brief; don't contradict them.

- `line_chart.series[].values` must have exactly one number per `xLabels` entry, in
  the same order (e.g. 5 `xLabels` years → 5 `values` per series). This is enforced
  server-side; a mismatched length is rejected.
- `comparison_table.rows[].values` must have exactly one value per `columns` entry,
  in the same order. Also enforced server-side.
- `node_diagram.nodes` reads left-to-right (or top-to-bottom on 9:16) as a sequence,
  not a free-form graph — order them in the sequence you want shown.
- `map.pins[].lon`/`lat` must be real coordinates for the named places (lon/lat
  bounds are enforced server-side); `stats` lines are invented-but-plausible like
  the chart fields, e.g. `"Pop: 1.2M"`, `"GDP: €98bn"`, `"Tech · Pharma"`.

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
