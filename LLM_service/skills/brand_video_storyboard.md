# Brand Video Storyboard — dynamic composition skill

Supersedes `brand_video.md`'s fixed 3-scene spec. The `media_producer` hands this
file to the LLM (`generate_video_storyboard`), which returns DATA only (no visual
code) matching `core.video_schema.StoryboardSpec`. Rendering the actual MP4
(Remotion + headless Chromium) is intentionally **external** to this service; edit
this file to retune the spec without touching code.

## Follow the agreed video direction when one is given

When the request includes an **agreed video direction** (the consensus from the
content roundtable — the visual tone, pacing, key beats, and on-screen call to
action), treat it as the primary creative brief: it was decided by the panel, not
guessed from the caption. Let it drive which slide types you choose and their order —
the hook beat it names, the proof/stat beat, the visual payoff, the closing CTA. The
post copy is supporting context for wording; the direction governs the *shape* of the
video. When no direction is given, compose from the topic and copy as usual.

## You are composing, not filling in a template

You do not pick between two fixed video formats. You compose a **storyboard**: an
ordered list of 2-8 `slides`, each one a typed building block from the registry
below. Choose which slide types to use, how many, and in what order, based on what
best tells this brand's story (and the agreed direction above, when present) — a
stat-heavy launch might lean on `counter_stat` and `collage`; a simple announcement
might be just `hook` → `outro`.

You may **only** use the slide types defined here — the JSON Schema you're given
enumerates them via the `type` discriminator. Never invent a new slide type.

## The slide registry

- **`hook`** — the scroll-stopping opening line, optionally with a cut-out image on
  a geometric shape behind it. Almost always the first slide. Optional `kicker` is a
  tiny ALL-CAPS eyebrow above the headline ('NOW LIVE', 'INTRODUCING'). Pick a
  `variant`: *spotlight* (default — image on a shape, headline below), *poster* (no
  image, giant headline over a gradient — bold and typographic; great for a text-only
  open), or *split* (image fills a diagonal half, headline the other — dynamic, needs
  an `imageQuery`). Optional `background`: solid / gradient / orbs / grid.
- **`counter_stat`** — 1-4 stat/feature cards (a number or claim + label + icon).
  Use when the brief has concrete numbers or proof points worth dwelling on. Pick a
  `variant`: *cards* (default — stacked cards), *orbit* (one hero stat huge in the
  centre, the rest around it — use to spotlight a single headline number; set
  `emphasisIndex` to choose which), or *ticker* (full-width rows whose accent bar
  grows as the value counts up — good for 3-4 equally-weighted stats).
- **`collage`** — 1-4 images arranged on geometric shapes, with an optional header.
  Use for visual storytelling (product, team, lifestyle) rather than numbers. `layout`:
  *grid*/*scatter*/*stack* (circles), *filmstrip* (a horizontal strip that slowly pans),
  or *polaroid* (white-bordered cards that drop in rotated). Optional `captions` (one
  short label per image, same order as `imageQueries`).
- **`pie_chart`** — 2-6 proportional segments, optionally with a short stat callout.
  Use for "how the whole breaks down" stories (budget split, market share). `variant`:
  *classic* (default — filled pie), *donut* (thick ring with the `calloutText` shown big
  in the hole — pick for one dominant share), or *exploded* (segments separated by gaps —
  pick to stress distinct parts). Optional `paletteName` and `source` (attribution line).
- **`line_chart`** — 1-2 trend lines drawn across 2-8 x-axis points (e.g. years).
  Use for "this changed over time" stories. Two series invites comparison. `variant`:
  *classic* (default), *area_glow* (a glowing gradient fill under a single hero line —
  use with ONE series), or *step_reveal* (a scrubber sweeps across the timeline). Optional
  `annotation` (a callout near the final point, e.g. 'All-time high'), `paletteName`, `source`.
- **`bar_chart`** — 2-6 bars compared side by side. Use for ranking or comparing a
  handful of discrete things at a single point in time (not a trend). `variant`: *columns*
  (default — vertical bars), *race* (horizontal bars sorted high-to-low with counting
  values — pick for a ranking), or *lollipop* (thin stems + circle heads — a cleaner look).
  Optional `highlightIndex` (emphasise one bar with a glow), `paletteName`, `source`.
- **`node_diagram`** — 3-6 short concept labels shown as a connected chain. Use to
  show how one idea leads to another (cause → effect, theme → theme). `variant`:
  *chain* (default — a sequence), *hub* (first node is a centre, the rest radiate out —
  hub-and-spoke), or *steps* (an ascending numbered staircase — an ordered process).
- **`comparison_table`** — 1-4 columns × 2-5 rows, revealed one row at a time. Use
  when there are several named things being compared on the same few attributes.
  `variant`: *rows* (default), *versus* (a two-column head-to-head with a centre 'VS'
  badge — use with EXACTLY 2 columns), or *scorecard* (cells as pills with the winning
  column marked — set `highlightColumn` to the 0-based winning column).
- **`map`** — a country/region map with 1-5 animated location pins, each with a
  `label` and up to 3 short `stats` lines. Use whenever the story is about *places*
  (cities, offices, markets, regional expansion). `region` is the ISO 3166-1
  alpha-2 country code, UPPERCASE (e.g. `"IE"` for Ireland); each pin needs real
  WGS84 coordinates — `lon` (negative = west) and `lat` — e.g. Dublin is
  lon `-6.26`, lat `53.35`. Whenever a pin is anything more specific than a whole
  city — a stadium, a parliament building, a neighbourhood, an address — ALSO set
  the pin's `query` to a full geocoding query in `"Venue, City, Country"` form
  (e.g. `"Aviva Stadium, Dublin, Ireland"`): a later step resolves it to precise
  coordinates, using your lon/lat only as a hint and fallback. Prefer this over
  `generated` for ANY map-like request. `variant`: *pins* (default — locations drop
  in) or *journey* (an animated route line connects the pins in order before their
  cards reveal — use for a tour or expansion story).
- **`outro`** — brand name, call-to-action button, optional contact handle, optional
  `tagline` (a short sign-off line under the brand name). Always the last slide. Pick
  a `variant`: *badge* (default — centred brand name + CTA pill) or *sweep* (the
  brand-name letters cascade in over a diagonal gradient — more cinematic).
- **`generated`** — the storyboard's SIGNATURE-MOMENT scene: a bespoke visual,
  authored as real code by a separate agent, for the one beat in the story that
  deserves a form no fixed type has — a timeline, a custom infographic, a process
  or metaphor animation, an unusual data shape. Use it for **0-1 slides per
  storyboard**, placed at the story's emotional or informational peak; most
  storyboards won't need one, but when the brief's core idea doesn't map to a
  fixed type, reach for it with confidence rather than flattening the idea into a
  weaker fixed slide. Two hard rules still apply: (1) if a fixed type IS the
  natural form — a map brief uses `map`, a plain trend uses `line_chart` — use
  that type, not `generated`; (2) `data` MUST carry ALL the structured content the
  scene renders — numbers, labels, series, coordinates — as typed JSON values,
  with `description` saying only HOW to present it (a vivid, specific creative
  brief: layout, motion, mood). Bad: `description: "show Dublin's population of
  1.2M and Cork's of 0.2M as rising towers"` with `data: {}`. Good: the same
  `description` with `data: {"cities": [{"name": "Dublin", "pop": 1200000},
  {"name": "Cork", "pop": 220000}]}`.

  Two more worked examples for the "signature moment" shapes this is meant for:

  - **Timeline.** Bad: `description: "show our journey from 2021 startup to
    2026 category leader"` with `data: {}` — nothing for the component to
    actually render. Good: `description: "a horizontal timeline sweeping
    left-to-right, each milestone's dot popping in with its year and one-line
    caption, the line itself drawing on as it goes"` with `data: {"milestones":
    [{"year": "2021", "caption": "Founded in a garage"}, {"year": "2023",
    "caption": "10,000th customer"}, {"year": "2026", "caption": "Category
    leader"}]}`.
  - **Process / metaphor animation.** Bad: `description: "show how our
    recycling process works"` with `data: {"summary": "collect, sort,
    reprocess"}` (a single opaque string the component would have to invent
    structure from). Good: `description: "three connected stages left-to-right,
    each with an icon and a short label, an arrow animating between each as it
    completes"` with `data: {"stages": [{"label": "Collect", "icon": "♻"},
    {"label": "Sort", "icon": "▤"}, {"label": "Reprocess", "icon": "✦"}]}`.

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
  bounds are enforced server-side); set `query` too for venue/address-level pins
  (see the registry entry above). `stats` lines are invented-but-plausible like
  the chart fields, e.g. `"Pop: 1.2M"`, `"GDP: €98bn"`, `"Tech · Pharma"` — but
  when the brief describes real events at each place, use the brief's own facts
  (event name, date, what happens there) instead of inventing.

## Theme and colour palette rules

- `theme`: `"dark"` (the default) or `"light"`. It drives the text colour on every
  slide (white text on dark, near-black text on light) and which map style a `map`
  slide's basemap uses. **If the brief asks for a white/light background or
  black/dark text, set `theme: "light"`** — do not try to express that through the
  colours alone.
- `primaryColor`: the background. Near-black for `theme: "dark"` (e.g. `#0d1117`,
  `#1a0a0f`); near-white for `theme: "light"` (e.g. `#f8fafc`, `#ffffff`). It must
  match the theme — a light primaryColor with `theme: "dark"` (or vice versa) makes
  text unreadable.
- `secondaryColor`: the dominant brand colour — card borders, button gradient start.
- `accentColor`: a complementary pop — shapes, button gradient end.
- All three must be 3- or 6-digit hex values (e.g. `#f5c84c`) — named colours are
  rejected server-side. They must contrast strongly against each other and against
  the theme's text colour. Derive them from the brand's industry, personality, and
  any colours mentioned in the brief.
- `backgroundStyle` (optional, storyboard-wide, drawn faintly behind EVERY slide):
  *solid* (default — flat background), *gradient* (a soft brand-colour wash),
  *aurora* (slow-drifting blurred brand orbs — premium/dynamic), or *grid* (a faint
  line grid — technical/data brands). It's an atmosphere, not a loud layer; keep it
  *solid* unless a consistent mood across the whole video clearly helps.
- `paletteName` (optional): the colour palette for chart/data marks across the video —
  *brand* (default — your accent+secondary), *vivid*, *pastel*, *duotone* (only your
  two brand colours), *heat* (warm sequential), *ocean* (cool sequential), or *mono*
  (monochrome). Charts can override it per-slide with their own `paletteName`.
- `transition` (optional, storyboard-wide): how each slide gives way to the next —
  *none* (default — a hard cut), *fade* (a soft crossfade, calm/premium), *slide* (the
  next slide pushes in, energetic), or *wipe* (a bold directional wipe). One choice
  applies to the whole video; pick to match the brand's energy.

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

## Audio — music (on `audio`) + per-slide narration (on each slide)

A later step generates a music track and a spoken voiceover and mixes them into the
render — you only choose the direction, never a URL or audio file.

### Per-slide narration (`narration` on each slide) — this is how the voice stays in sync

Give **each slide its own `narration`**: one natural spoken sentence the voiceover says
*while that slide is on screen*. This is what keeps the audio matched to the visuals —
the narration for the stat slide plays over the stat slide, the outro line over the
outro, and so on.

- Write it to be **heard**, not read: natural spoken rhythm, and it should **complement**
  the slide (add context, momentum, a reason to care), not just read the slide's headline
  back verbatim.
- Keep each line **tight** — usually one short sentence. The video automatically stretches
  each slide to fit its line, so you never need to cram, but don't pad either.
- Together the lines should tell one continuous story across the slides: open on the
  hook's idea, build through the middle, land on the outro's call to action.
- A slide may set `narration` to `null` for a beat that plays under music alone.

Prefer this per-slide `narration` over the whole-video `audio.narrationScript` (the latter
is a fallback for the rare case you want a single voiceover not tied to slides — leave it
null when you give per-slide narration).

### Music (`audio` block)

Always include an `audio` object. Pick music that matches the brand's energy and the story:
- `musicMood`: *inspiring*, *uplifting*, *energetic*, *calm*, *dramatic*, or *playful*.
- `musicGenre`: *corporate*, *cinematic*, *electronic*, *acoustic*, *hiphop*, or *ambient*.
- `musicEnergy`: *low*, *medium*, or *high* — match the `transition`/`backgroundStyle`
  energy (a calm, faded, aurora video wants *low*; a punchy, slide/wipe video wants *high*).
- `narrationVoice`: the voice persona that best fits the brand — *warm* (friendly,
  approachable), *energetic* (upbeat, dynamic), *authoritative* (confident, serious), or
  *friendly* (bright, casual). One voice narrates the whole video.

Use ONLY the listed values for music fields — anything else is rejected server-side.

Return only valid structured data — no explanation.
