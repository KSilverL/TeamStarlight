// Design tokens shared by every slide component (and importable by LLM-generated
// bespoke scenes). Sized for the 1080-wide canvas both aspect ratios share —
// 1080x1920 (9:16) and 1920x1080 (16:9) — so a token reads the same physical size
// in either orientation at typical short-form viewing distance.
//
// Values that existed as inline literals before this module were hoisted verbatim
// (headline 40 / hook 64 / outro 52 / stat 44 ...) so the refactor is a pure
// substitution, not a redesign.

export const fontSize = {
  /** Oversized poster type (hook "poster" variant, hero numbers) */
  display: 96,
  /** Hook headline */
  h1: 64,
  /** Outro brand name */
  title: 52,
  /** Stat card value */
  stat: 44,
  /** Standard slide headline (the h2 every slide shares) */
  headline: 40,
  /** Chart callouts, node labels upper bound */
  subhead: 32,
  /** Hook subtext, section labels */
  body: 28,
  /** CTA button, node text */
  label: 24,
  /** Legends, table cells, stat labels */
  caption: 20,
  /** Chart axis ticks */
  tick: 16,
} as const;

/** 8-based spacing scale: space(2)=16, space(3)=24 ... */
export const space = (n: number): number => n * 8;

export const radius = {
  /** Stat cards */
  card: 18,
  /** Diagram nodes */
  node: 16,
  /** Table label cells */
  cell: 12,
  /** Chart bars (svg rx) */
  bar: 6,
  /** CTA buttons, legend badges */
  pill: 999,
} as const;

export const letterSpacing = {
  tight: -1,
  normal: 0,
  /** Outro brand name */
  wide: 2,
  /** Kickers / section labels, ALL-CAPS microcopy */
  caps: 4,
} as const;

/**
 * A soft glow in the given colour — emphasis treatment for hero stats, winning
 * cells, chart leaders. Returns a `boxShadow` value; pass to `filter` via
 * `dropGlow` for SVG/irregular shapes instead.
 */
export const accentGlow = (color: string, strength: number = 24): string =>
  `0 0 ${strength}px ${color}`;

/** `filter: dropGlow(...)` — the glow that follows a shape's alpha, not its box. */
export const dropGlow = (color: string, strength: number = 12): string =>
  `drop-shadow(0 0 ${strength}px ${color})`;
