# Posting plan — campaign scheduling skill

`plan_campaign` reads this file and injects it as the static planning layer when
composing a multi-date posting plan (strategy + schedule, **never copy**). Edit it to
retune scheduling heuristics without touching code. All times are in the audience's
local time zone.

## What a plan is (and isn't)
- A plan is a **dated sequence of strategic intents** — what to post, when, and why.
- It is **not** the copy. Never write the actual post here; that happens later, per slot,
  on the planned day (riding that day's trends + brand/user rules).
- Three fields, three jobs — keep them distinct:
  - `topic` — one short line; it becomes the brief's topic **verbatim** (e.g. "behind the
    scenes: our roast profile"). Not a sentence, not a hook.
  - `angle` — the specific hook or lens for that topic ("the one variable most roasters
    ignore").
  - `rationale` — the strategy argument: *why this topic, on this date, in this position*.

## Scheduling heuristics
- **Best windows by platform** (local time):
  - **LinkedIn** — Tue/Wed/Thu mornings (07:30–09:30) or lunch (11:30–13:00). B2B, weekdays.
  - **Instagram** — weekday evenings (18:00–21:00) and weekend late mornings (10:00–12:00).
  - **Twitter/X** — weekday commute peaks (08:00–09:00, 17:00–18:00) and live-moment windows.
  - **Facebook** — weekday mid-mornings (09:00–11:00) and early afternoons (13:00–15:00);
    strong on weekends for community/story posts.
  - **TikTok** — early morning (06:00–09:00) and evening (19:00–23:00); post when the target
    demographic is idle-scrolling, not at work.
- **Default cadence** when the caller gives none: 2–3 posts per platform per week. Never two
  posts on the same platform on consecutive days unless the campaign is event-driven
  (launch, countdown).
- Respect any explicit `cadence_hint` and window from the caller over these defaults.

## The campaign arc
- Map slot position to funnel stage: **early = awareness** (broad hook / value), **mid =
  consideration** (education, story, behind-the-scenes), **late = conversion** (proof,
  testimonials, a clear ask).
- Front-load reach, back-load the CTA. The final slot should close the arc toward the goal.

## Topic mix
- Rotate the angle across slots — cycle through: **educate** (how/why), **story** (behind
  the scenes, customer), **proof** (numbers, results), **conversation** (question, hot
  take), and **promotion**. At most **1 in 3** slots may be directly promotional.
- Consecutive slots must not repeat the same angle on the same platform.
- The plan is a **series**: later slots may explicitly build on earlier ones ("part 2", "as
  promised last week"), and the final slot should tie the arc together.
- Match the topic to the platform's strength — B2B insight to LinkedIn, a visual/sensory
  beat to Instagram, a sharp take to X, a community story to Facebook.

## Rationale discipline
- Every slot's `rationale` must say WHY this topic on this date — tie it to the window
  position (early/mid/late), the platform's rhythm, a real date hook (weekday, season,
  event), or a prior slot it builds on. "Good engagement" alone is not a rationale.
- One tight sentence is enough; make the causal link explicit.

## Trends
- When a CURRENT TRENDS block is present, fuse a trend into **at most 1–2 slots** where the
  connection is genuine, and name the trend in that slot's rationale. A forced trend is
  worse than none; undated evergreen slots are fine.

## Self-check before returning the plan
- Does every slot have a distinct `angle` from its neighbours on the same platform?
- Is ≤ 1 in 3 slots promotional, and does the arc move awareness → consideration → conversion?
- Does each `rationale` name a concrete reason (position / rhythm / date hook / prior slot)?
- Are all dates within the requested window, and does the final slot close toward the goal?
