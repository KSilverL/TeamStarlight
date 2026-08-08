// The maths behind the pixel-mosaic backdrop: a coarse grid of squares, each the
// same hue family at a different lightness, undulating slowly. Everything here is
// pure and React-free so it stays unit-testable — vitest.config.ts only includes
// `src/design/**/*.test.ts` in a *node* environment, so anything that imports
// `remotion` or renders JSX can't be covered. The <PixelMosaic> component in
// backdrops.tsx is the thin JSX shell over these functions.
//
// Every value is a pure function of (col, row, frame) — never wall-clock time and
// never Math.random — for the same reason the rest of design/ is: Remotion may
// render frame ranges on separate worker processes, and a mosaic that disagrees
// with itself between workers produces a visibly seamed video.

import { mixHex } from "./palettes";

const clamp01 = (t: number): number => Math.min(1, Math.max(0, t));

// ── Grid ──────────────────────────────────────────────────────────────────────

export interface MosaicGrid {
  /** Cell edge length in px (square). */
  cell: number;
  cols: number;
  rows: number;
}

/** Hard ceiling on cells so a hand-written fixture can't spawn thousands of DOM nodes. */
const MAX_CELLS = 400;

/**
 * Grid geometry for a frame. The cell size is derived from the **short** edge, not
 * the width: the pipeline renders 1080×1920, 1920×1080 and 1080×1080, and sizing
 * off the width would make a landscape frame 6 cells wide by 4 tall — comically
 * coarse. Short-edge sizing keeps the physical cell identical across all three.
 *
 *   1080×1920 → cell 180 → 6 × 11
 *   1920×1080 → cell 180 → 11 × 6
 *   1080×1080 → cell 180 → 6 × 6
 *
 * `cols`/`rows` cover the frame (ceil), so the last row/column may overhang — the
 * component clips it.
 */
export const mosaicGrid = (
  width: number,
  height: number,
  cellsAcrossShortEdge: number = 6,
): MosaicGrid => {
  const across = Math.max(2, Math.round(cellsAcrossShortEdge));
  const cell = Math.min(width, height) / across;
  const cols = Math.max(1, Math.ceil(width / cell));
  const rows = Math.max(1, Math.ceil(height / cell));
  return { cell, cols, rows };
};

/** Whether a grid is small enough to draw as DOM nodes (see MAX_CELLS). */
export const isDrawableGrid = (grid: MosaicGrid): boolean => grid.cols * grid.rows <= MAX_CELLS;

// ── Deterministic hashing ─────────────────────────────────────────────────────

/**
 * 32-bit integer avalanche (the murmur3 finalizer). `Math.imul` is spec-exact
 * 32-bit multiplication, so this produces bit-identical output on every machine,
 * JIT tier and Chromium build.
 *
 * Deliberately NOT the ubiquitous `fract(sin(x * 12.9898) * 43758.5453)` shader
 * trick: that one's low bits depend on the platform's sin() implementation, which
 * is exactly the kind of drift that makes two render workers disagree.
 */
const mix32 = (n: number): number => {
  let h = Math.imul(n ^ (n >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  return (h ^ (h >>> 16)) >>> 0;
};

/**
 * Deterministic 0..1 value for a lattice point. The three large primes are the
 * standard spatial-hash constants; they matter because a naive `x + y * cols`
 * would make the hash symmetric in x/y, and a symmetric hash turns the dissolve
 * (§ cellAlpha) into diagonal stripes instead of a scatter.
 */
export const hashUnit = (x: number, y: number, z: number = 0, seed: number = 0): number =>
  mix32(
    (Math.imul(x | 0, 73856093) ^ Math.imul(y | 0, 19349663) ^ Math.imul(z | 0, 83492791)) + seed,
  ) / 4294967296;

// ── Value noise ───────────────────────────────────────────────────────────────

/** Hermite smoothstep — the standard ease that removes the lattice's linear creases. */
const smooth = (t: number): number => t * t * (3 - 2 * t);

const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/**
 * Trilinearly-interpolated 3D value noise in [0,1]: smooth in space *and* in the
 * third axis, which is what we drive with frame number.
 *
 * Spatial coherence is the whole point. Giving every cell its own independent sine
 * phase (the obvious cheaper approach) makes the grid flicker like static;
 * sampling a shared smooth field makes neighbouring cells drift *together*, which
 * is the slow undulation the reference video has.
 */
export const valueNoise3 = (x: number, y: number, z: number, seed: number = 0): number => {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const zi = Math.floor(z);
  const tx = smooth(x - xi);
  const ty = smooth(y - yi);
  const tz = smooth(z - zi);

  const corner = (dx: number, dy: number, dz: number) => hashUnit(xi + dx, yi + dy, zi + dz, seed);

  const y0z0 = lerp(corner(0, 0, 0), corner(1, 0, 0), tx);
  const y1z0 = lerp(corner(0, 1, 0), corner(1, 1, 0), tx);
  const y0z1 = lerp(corner(0, 0, 1), corner(1, 0, 1), tx);
  const y1z1 = lerp(corner(0, 1, 1), corner(1, 1, 1), tx);

  return lerp(lerp(y0z0, y1z0, ty), lerp(y0z1, y1z1, ty), tz);
};

export interface MosaicShadeOptions {
  /**
   * Lattice units per cell. 0.7 ≈ a 1.4-cell feature, so ADJACENT cells land at
   * visibly different shades while still drifting together.
   *
   * This value is the difference between "a grid of squares" and "a soft gradient":
   * measured against the reference video (peak |d(blue)/dx| across a scanline), a
   * 0.32 scale gives neighbouring cells about a third of the reference's contrast
   * and the grid stops reading as pixels at all.
   */
  noiseScale?: number;
  /** Frames per lattice step along the time axis. 240 ≈ one step per 8s at 30fps. */
  speedFrames?: number;
  seed?: number;
}

/**
 * This cell's position along the colour ramp at this frame, in [0,1].
 *
 * The defaults put the motion in the same register as BackdropOrbs' existing drift
 * (`t = frame * speed / 60`): felt, not seen. Faster and the background starts
 * competing with the text for attention, which is the failure mode of every
 * animated-gradient backdrop.
 */
export const mosaicShade = (
  col: number,
  row: number,
  frame: number,
  opts: MosaicShadeOptions = {},
): number =>
  valueNoise3(
    col * (opts.noiseScale ?? 0.7),
    row * (opts.noiseScale ?? 0.7),
    frame / (opts.speedFrames ?? 240),
    opts.seed ?? 0,
  );

// ── Colour ramp ───────────────────────────────────────────────────────────────

// Hue basis: blends of the brand's two non-background colours. Each stop is then
// pulled toward primaryColor by an increasing amount, producing a single-hue-family
// lightness ladder rather than a set of distinguishable hues.
const RAMP_TOWARD_PRIMARY = [0, 0.18, 0.38, 0.58, 0.78, 1];

/**
 * Six ramp stops derived from the storyboard's brand colours.
 *
 * The last stop IS `primaryColor`, which is what makes this automatically
 * theme-correct: primaryColor already encodes light-vs-dark (near-white for a light
 * storyboard, near-black for a dark one), so the same recipe produces the
 * reference's pale blue→lavender field on light and its inverse on dark, with no
 * `theme` parameter anywhere.
 *
 * `contrast` (0..1) pulls *every* stop toward primaryColor — the legibility knob.
 * Near-black text over the mosaic needs the darkest stop to stay light, and 0.85 is
 * the value the slides use. contrast=1 is the full-range ramp; contrast=0 collapses
 * to a flat primaryColor field.
 *
 * NOT built on paletteFor(): that resolves *categorical* mark colours (six mutually
 * distinguishable hues for chart series), which is the exact opposite of what a
 * single-hue lightness ramp needs. mixHex is the honest reuse here.
 */
export const mosaicRamp = (
  primaryColor: string,
  secondaryColor: string,
  accentColor: string,
  contrast: number = 1,
): string[] => {
  const c = clamp01(contrast);
  const basis = [
    secondaryColor,
    mixHex(secondaryColor, accentColor, 0.5),
    accentColor,
    mixHex(accentColor, secondaryColor, 0.35),
    mixHex(secondaryColor, accentColor, 0.2),
    secondaryColor,
  ];
  return basis.map((hue, i) => mixHex(hue, primaryColor, 1 - (1 - RAMP_TOWARD_PRIMARY[i]) * c));
};

/** Sample a ramp at t∈[0,1], interpolating between adjacent stops. */
export const rampColor = (t: number, ramp: string[]): string => {
  if (ramp.length === 0) return "#000000";
  const last = ramp.length - 1;
  if (last === 0) return ramp[0];
  const scaled = clamp01(t) * last;
  const i = Math.min(Math.floor(scaled), last - 1);
  return mixHex(ramp[i], ramp[i + 1], scaled - i);
};

// ── Dissolve ──────────────────────────────────────────────────────────────────

/**
 * Opacity of one cell during a dissolve. `threshold` is the cell's fixed place in
 * the scatter order (a hashUnit value); `dissolve` runs 0 (fully painted) → 1
 * (fully gone) and each cell fades over a `feather`-wide window around its own
 * threshold rather than popping.
 *
 * Running `dissolve` backwards re-forms the mosaic through the same order, so
 * reveal and conceal share one code path — there is no second function.
 */
export const cellAlpha = (threshold: number, dissolve: number, feather: number = 0.18): number => {
  const f = Math.max(1e-6, feather);
  const t = clamp01(threshold);
  // The cell's fade window is [t*(1-f), t*(1-f) + f]. Compressing the start by
  // (1-f) is what makes the LAST cell finish exactly at dissolve=1 instead of still
  // being mid-fade when the reveal is over.
  //
  // Written as `dissolve - t + t*f` rather than the algebraically identical
  // `dissolve - t * (1 - f)`: at t=1, dissolve=1 the first form yields exactly `f`
  // (so alpha is exactly 0), while the second accumulates rounding and leaves a
  // 3e-16 opacity behind — enough to defeat the caller's `alpha <= 0` skip and keep
  // painting a cell that should be gone.
  return 1 - clamp01((dissolve - t + t * f) / f);
};
