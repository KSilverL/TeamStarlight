# Posting plan — campaign scheduling skill

`plan_campaign` reads this file and injects it as the static planning layer when
composing a multi-date posting plan (strategy + schedule, never copy). Edit it to
retune scheduling heuristics without touching code.

## Scheduling heuristics
- Best windows by platform: LinkedIn — Tue/Wed/Thu mornings (07:30–09:30) or lunch;
  Instagram — weekday evenings (18:00–21:00) and weekend late mornings; Twitter/X —
  weekday commute peaks (08:00–09:00, 17:00–18:00) and live-moment windows.
- Default cadence when the caller gives none: 2–3 posts per platform per week.
  Never two posts on the same platform on consecutive days unless the campaign is
  event-driven (launch, countdown).
- Front-load awareness, back-load conversion: open the window with broad hook/value
  posts, close it with proof (results, testimonials) and a clear call to action.

## Topic mix
- Vary the angle across slots — rotate between: educate (how/why), story (behind the
  scenes, customer), proof (numbers, results), conversation (question, hot take),
  and promotion. At most 1 in 3 slots may be directly promotional.
- Consecutive slots must not repeat the same angle on the same platform.
- The plan is a SERIES: later slots may explicitly build on earlier ones ("part 2",
  "as promised last week"), and the final slot should close the arc toward the goal.

## Rationale discipline
- Every slot's `rationale` must say WHY this topic on this date — tie it to the
  window position (early/mid/late), the platform's rhythm, a real date hook
  (weekday, season, event), or a prior slot it builds on. "Good engagement" alone
  is not a rationale.
- `topic` is one short line (it becomes the brief's topic verbatim); the specific
  hook goes in `angle`, the strategy argument in `rationale`.

## Trends
- When a CURRENT TRENDS block is present, fuse a trend into at most 1–2 slots where
  the connection is genuine, and name the trend in that slot's rationale. A forced
  trend is worse than none; undated evergreen slots are fine.
