// Motion presets: the spring/interpolate choreography that used to be copy-pasted
// (with slightly drifting constants) across every slide component, canonicalized
// as pure functions of (frame, fps). Each entrance returns a spreadable style
// fragment ({ opacity, transform, ... }); choreography helpers (stagger, countUp,
// progress) return plain numbers.
//
// Everything is a pure function of the current frame — never wall-clock time —
// so renders stay frame-deterministic (the same rule that forces
// isAnimationActive={false} on Recharts).

import { interpolate, spring } from "remotion";

export interface EntranceStyle {
  opacity: number;
  transform: string;
  filter?: string;
  clipPath?: string;
}

const clampBoth = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Frame delay for the i-th element of a staggered group. */
export const stagger = (index: number, stepFrames: number = 6): number => index * stepFrames;

/** Raw spring progress (0→1 with overshoot) — for custom transforms like bar growth. */
export const springEnter = (
  frame: number, fps: number,
  opts: { delay?: number; damping?: number; mass?: number } = {},
): number =>
  spring({
    frame: frame - (opts.delay ?? 0),
    fps,
    config: { damping: opts.damping ?? 16, ...(opts.mass !== undefined ? { mass: opts.mass } : {}) },
  });

/** Plain fade-in over `frames`, starting at `delay`. */
export const fadeIn = (frame: number, opts: { delay?: number; frames?: number } = {}): number =>
  interpolate(frame - (opts.delay ?? 0), [0, opts.frames ?? 12], [0, 1], clampBoth);

/**
 * Rise-and-fade: translateY from `distance` to 0 while fading in — the headline
 * entrance HookSlide always used (opacity over 12 frames, rise over 15).
 */
export const riseSoft = (
  frame: number,
  opts: { delay?: number; distance?: number; fadeFrames?: number; riseFrames?: number } = {},
): EntranceStyle => {
  const t = frame - (opts.delay ?? 0);
  return {
    opacity: interpolate(t, [0, opts.fadeFrames ?? 12], [0, 1], clampBoth),
    transform: `translateY(${interpolate(t, [0, opts.riseFrames ?? 15], [opts.distance ?? 30, 0], clampBoth)}px)`,
  };
};

/** Spring scale-up from 0 with a quick fade — collage circles, diagram nodes. */
export const popScale = (
  frame: number, fps: number,
  opts: { delay?: number; damping?: number; mass?: number; fadeFrames?: number } = {},
): EntranceStyle => ({
  opacity: fadeIn(frame, { delay: opts.delay, frames: opts.fadeFrames ?? 10 }),
  transform: `scale(${springEnter(frame, fps, opts)})`,
});

/**
 * Spring slide-in from a direction with a quick fade — stat cards (from the
 * right, 60px), table rows (from the right, 40px).
 */
export const slideIn = (
  frame: number, fps: number,
  opts: { delay?: number; damping?: number; distance?: number; axis?: "x" | "y"; fadeFrames?: number } = {},
): EntranceStyle => {
  const enter = springEnter(frame, fps, opts);
  const offset = (1 - enter) * (opts.distance ?? 60);
  return {
    opacity: fadeIn(frame, { delay: opts.delay, frames: opts.fadeFrames ?? 10 }),
    transform: opts.axis === "y" ? `translateY(${offset}px)` : `translateX(${offset}px)`,
  };
};

/** Blur-to-sharp fade — soft/premium entrance for large type or images. */
export const blurIn = (
  frame: number,
  opts: { delay?: number; frames?: number; maxBlur?: number } = {},
): EntranceStyle => {
  const t = frame - (opts.delay ?? 0);
  const frames = opts.frames ?? 15;
  return {
    opacity: interpolate(t, [0, frames], [0, 1], clampBoth),
    transform: "none",
    filter: `blur(${interpolate(t, [0, frames], [opts.maxBlur ?? 12, 0], clampBoth)}px)`,
  };
};

/** Clip-path wipe reveal from a direction — panels, split layouts, images. */
export const maskWipe = (
  frame: number,
  opts: { delay?: number; frames?: number; from?: "left" | "right" | "top" | "bottom" } = {},
): EntranceStyle => {
  const t = frame - (opts.delay ?? 0);
  const p = interpolate(t, [0, opts.frames ?? 18], [100, 0], clampBoth);
  const inset = {
    left: `inset(0 ${p}% 0 0)`,
    right: `inset(0 0 0 ${p}%)`,
    top: `inset(0 0 ${p}% 0)`,
    bottom: `inset(${p}% 0 0 0)`,
  }[opts.from ?? "left"];
  return { opacity: 1, transform: "none", clipPath: inset };
};

/**
 * Exit: fade while dropping slightly — begins `leadFrames` before the slide's
 * end so motion resolves before the cut. Multiply/compose with an entrance's
 * opacity when using both.
 */
export const fadeDrop = (
  frame: number, durationFrames: number,
  opts: { leadFrames?: number; distance?: number } = {},
): EntranceStyle => {
  const lead = opts.leadFrames ?? 12;
  const start = durationFrames - lead;
  return {
    opacity: interpolate(frame, [start, durationFrames], [1, 0], clampBoth),
    transform: `translateY(${interpolate(frame, [start, durationFrames], [0, opts.distance ?? 20], clampBoth)}px)`,
  };
};

/** Exit: shrink-and-fade ending at the slide's last frame. */
export const scaleAway = (
  frame: number, durationFrames: number,
  opts: { leadFrames?: number; minScale?: number } = {},
): EntranceStyle => {
  const lead = opts.leadFrames ?? 12;
  const start = durationFrames - lead;
  return {
    opacity: interpolate(frame, [start, durationFrames], [1, 0], clampBoth),
    transform: `scale(${interpolate(frame, [start, durationFrames], [1, opts.minScale ?? 0.92], clampBoth)})`,
  };
};

/**
 * Slow continuous zoom (plus optional pan) across an element's whole life — the
 * Ken Burns move, used both on stock footage and, at a much smaller amplitude
 * (to: 1.035), to creep a text block toward the viewer over its slide.
 *
 * Returns a transform STRING rather than an EntranceStyle: it is meant to be
 * concatenated with an entrance's own transform, not to replace it. Pan is in
 * percent of the element's own box, so it behaves identically at any resolution.
 *
 * `Math.max(durationFrames, 1)` is not defensive padding — `interpolate` throws on
 * a non-increasing input range, so a hand-written fixture with durationFrames: 0
 * would hard-fail the whole render instead of rendering a still frame.
 */
export const kenBurns = (
  frame: number,
  durationFrames: number,
  opts: { from?: number; to?: number; panX?: number; panY?: number } = {},
): string => {
  const t = interpolate(frame, [0, Math.max(durationFrames, 1)], [0, 1], clampBoth);
  const from = opts.from ?? 1;
  const scale = from + ((opts.to ?? 1.12) - from) * t;
  return `scale(${scale}) translate(${(opts.panX ?? 0) * t}%, ${(opts.panY ?? 0) * t}%)`;
};

/** 0→1 progress between two frames, clamped — SVG draw-ons, sweeps, scrubbers. */
export const progress = (frame: number, opts: { from?: number; to: number }): number =>
  interpolate(frame, [opts.from ?? 0, opts.to], [0, 1], clampBoth);

/**
 * Odometer count-up to `target` over `frames`, starting at `delay` — extracted
 * from CounterStatSlide (30-frame ramp). Returns the rounded in-flight value;
 * format with toLocaleString() at the call site.
 */
export const countUp = (
  frame: number, target: number,
  opts: { delay?: number; frames?: number } = {},
): number =>
  Math.round(
    interpolate(frame - (opts.delay ?? 0), [0, opts.frames ?? 30], [0, target], clampBoth),
  );
