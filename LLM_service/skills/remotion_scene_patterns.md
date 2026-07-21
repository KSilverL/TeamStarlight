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

## 6. Recharts bar/line, frame-driven (not recharts' own animation)
```tsx
import { BarChart, Bar, XAxis, YAxis } from "recharts";

// Give BarChart/LineChart EXPLICIT width/height (in px, from useVideoConfig) — never
// ResponsiveContainer, which depends on a resize observer that doesn't fire reliably
// in a headless-Chromium still/frame render. See video_renderer/src/slides/LineChartSlide.tsx.
const chartWidth = width * 0.82;
const chartHeight = height * 0.4;
const reveal = interpolate(frame, [0, 30], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
const chartData = rows.map((r) => ({ ...r, value: r.value * reveal })); // grow bars toward their real value

<BarChart width={chartWidth} height={chartHeight} data={chartData}>
  <XAxis dataKey="label" stroke={textColor} tick={{ fill: textColor, fontSize: fontSize.tick }} />
  <YAxis hide />
  {/* isAnimationActive MUST be false — recharts' own animation is wall-clock-based
      and breaks deterministic frame rendering; drive motion via `reveal` above instead. */}
  <Bar dataKey="value" fill={accentColor} isAnimationActive={false} radius={[6, 6, 0, 0]} />
</BarChart>
```

## 7. d3-geo point projection (a map-LIKE `generated` scene, not the fixed `map` slide)
```tsx
import { geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-50m.json";

const countries = feature(world as any, (world as any).objects.countries) as any;
const projection = geoMercator().fitExtent([[40, 200], [width - 40, height - 400]], countries);
const path = geoPath(projection);
const [x, y] = projection([lon, lat]) ?? [0, 0]; // project one point (e.g. a city) onto the same frame

<svg width={width} height={height} style={{ position: "absolute" }}>
  <path d={path(countries) ?? undefined} fill="rgba(255,255,255,0.06)" stroke={secondaryColor} strokeWidth={1} />
  <circle cx={x} cy={y} r={interpolate(frame, [0, 20], [0, 10], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} fill={accentColor} />
</svg>
```

## 8. Text-overflow-safe labels (avoid the #1 visual-QA rejection: overlapping/clipped text)
```tsx
// Cap line length instead of trusting slide.data's string length — a brief can hand
// back a longer label than the layout was designed for.
const clamp = (s: string, max = 28) => (s.length > max ? s.slice(0, max - 1).trimEnd() + "…" : s);

<div style={{
  maxWidth: "84%",           // generous margins — never let text touch the canvas edge
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
}}>
  {clamp(row.label)}
</div>
// For a list of unknown length, also cap the ITEM COUNT rendered (e.g. `.slice(0, 5)`)
// rather than assuming slide.data arrives pre-trimmed to what the layout can fit.
```

## Rules that keep a scene renderable
- Call every hook (`useCurrentFrame`, `useVideoConfig`, `useMemo`, …) unconditionally at the top.
- `interpolate` input ranges must be strictly increasing and the same length as the output range; clamp the ends.
- Recharts: always `isAnimationActive={false}` and drive motion by interpolating props per frame.
- Read ALL content from `slide.data`; never hard-code copy or restate the brief as a plain text card.
- Clamp/truncate any text or list derived from `slide.data` to what the layout can actually
  fit (pattern 8) — a brief's data is free-form and can be longer than the design assumes.
