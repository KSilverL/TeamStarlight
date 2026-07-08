# Remotion scene patterns — snippets for `generated` slides

Proven, frame-deterministic building blocks for a bespoke Remotion scene. All derive
from `useCurrentFrame()` (never wall-clock time), so headless Chromium renders every
frame identically. Prefer the `../../design` helpers where one fits; reach for these
raw patterns when the design system doesn't already cover the effect.

## 1. SVG path draw-on (line/route/underline)
```tsx
const len = 400; // measured or estimated path length
const p = interpolate(frame, [0, 40], [0, 1], { extrapolateRight: "clamp" });
<path d={d} stroke={accentColor} strokeWidth={4} fill="none"
  strokeDasharray={len} strokeDashoffset={len * (1 - p)} />
```

## 2. Odometer counter (rising number)
```tsx
const value = Math.round(
  interpolate(frame - delay, [0, 30], [0, target], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
);
<span>{value.toLocaleString()}</span>   // or: import { countUp } from "../../design"
```

## 3. Staggered card grid (entrance choreography)
```tsx
{items.map((it, i) => {
  const delay = i * 5;                                   // or stagger(i, 5)
  const s = spring({ frame: frame - delay, fps, config: { damping: 15 } });
  const o = interpolate(frame - delay, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ opacity: o, transform: `scale(${s})` }}>{/* ... */}</div>;
})}
```

## 4. Radial burst reveal (items around a centre)
```tsx
{items.map((it, i) => {
  const a = (i / items.length) * Math.PI * 2 - Math.PI / 2;
  const R = Math.min(width, height) * 0.32;
  const grow = spring({ frame: frame - i * 6, fps, config: { damping: 16 } });
  const x = width / 2 + Math.cos(a) * R * grow;
  const y = height / 2 + Math.sin(a) * R * grow;
  return <div style={{ position: "absolute", left: x, top: y, transform: "translate(-50%,-50%)" }}>{/* ... */}</div>;
})}
```

## 5. Animated gradient backdrop (depth under the subject)
```tsx
// Prefer the design system: <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} />
<AbsoluteFill style={{
  background: `linear-gradient(135deg, ${secondaryColor}33 0%, transparent 45%, ${accentColor}33 100%)`,
}} />
```

## Rules that keep a scene renderable
- Call every hook (`useCurrentFrame`, `useVideoConfig`, `useMemo`, …) unconditionally at the top.
- `interpolate` input ranges must be strictly increasing and the same length as the output range; clamp the ends.
- Recharts: always `isAnimationActive={false}` and drive motion by interpolating props per frame.
- Read ALL content from `slide.data`; never hard-code copy or restate the brief as a plain text card.
