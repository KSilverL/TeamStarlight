// A second reference bespoke scene for the `generated`-slide codegen agent —
// demonstrates the `recharts` construction style (ExemplarScene.tsx demonstrates
// hand-rolled bars instead), since the codegen system prompt names recharts as an
// available import but no exemplar previously showed it working end-to-end. Lives
// two levels under src/ (same depth as a real src/generated/<job>/ component) so
// its "../../types" / "../../design" imports are byte-identical to what a
// generated file uses. LLM_service/core/services/azure.py reads this file at
// prompt-build time and embeds it verbatim as a second few-shot example.

import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Bar, BarChart, XAxis, YAxis } from "recharts";
import type { GeneratedSlide } from "../../types";
import {
  GradientWash,
  Kicker,
  SlideHeadline,
  bodyFont,
  countUp,
  displayFont,
  fadeIn,
  fontSize,
} from "../../design";

// A generated component receives exactly this prop shape (see registry.ts /
// Composition.tsx). Read all content from `slide.data`; never hard-code copy.
const ExemplarChartScene: React.FC<{
  slide: GeneratedSlide;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, secondaryColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  // Shape the data defensively — the brief's `data` is free-form JSON. Cap the
  // item count to what the chart can legibly fit (never trust the brief to have
  // pre-trimmed a list to the layout's capacity).
  const kicker = typeof slide.data.kicker === "string" ? slide.data.kicker : null;
  const headline = typeof slide.data.headline === "string" ? slide.data.headline : "";
  const bars = (Array.isArray(slide.data.bars) ? slide.data.bars : [])
    .slice(0, 6)
    .map((it: unknown) => {
      const row = it as { label?: unknown; value?: unknown };
      return { label: String(row.label ?? ""), value: Number(row.value ?? 0) };
    });
  const leader = bars.reduce((max, r) => (r.value > max ? r.value : max), 0);

  // Recharts' own animation is wall-clock-based and breaks deterministic
  // rendering — isAnimationActive is always false; motion instead comes from
  // interpolating each bar's plotted value toward its real value per frame.
  const growFrames = 30;
  const grow = interpolate(frame, [0, growFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const chartData = bars.map((r) => ({ ...r, plotted: r.value * grow }));

  const chartWidth = width * 0.82;
  const chartHeight = height * 0.36;
  const captionsOpacity = fadeIn(frame, { delay: growFrames, frames: 15 });

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {/* Layer 1 — backdrop */}
      <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} strength={0.2} />

      {/* Layer 2 — heading block, generous top margin */}
      <div style={{ position: "absolute", top: "8%", width: "100%", textAlign: "center" }}>
        {kicker && <Kicker color={accentColor}>{kicker}</Kicker>}
        <SlideHeadline color="#ffffff" top="0" size={fontSize.h1}>
          {headline}
        </SlideHeadline>
      </div>

      {/* Layer 3 — the chart itself, EXPLICIT width/height (never ResponsiveContainer,
          which needs a resize observer that doesn't fire reliably in a headless-Chromium
          still/frame render — see video_renderer/src/slides/LineChartSlide.tsx). */}
      <div
        style={{
          position: "absolute",
          top: "32%",
          left: "9%",
          width: "82%",
          display: "flex",
          justifyContent: "center",
        }}
      >
        <BarChart width={chartWidth} height={chartHeight} data={chartData}>
          <XAxis
            dataKey="label"
            stroke="#ffffff"
            tick={{ fill: "#ffffff", fontSize: fontSize.tick, fontFamily: bodyFont }}
          />
          <YAxis hide />
          <Bar dataKey="plotted" fill={accentColor} isAnimationActive={false} radius={[6, 6, 0, 0]} />
        </BarChart>
      </div>

      {/* Layer 4 — the leading bar's value, counting up, called out below the chart */}
      {leader > 0 && (
        <div
          style={{
            position: "absolute",
            bottom: "12%",
            width: "100%",
            textAlign: "center",
            opacity: captionsOpacity,
          }}
        >
          <span
            style={{
              color: accentColor,
              fontSize: fontSize.subhead,
              fontWeight: 800,
              fontFamily: displayFont,
            }}
          >
            {countUp(frame, leader, { delay: growFrames }).toLocaleString()}
          </span>
        </div>
      )}
    </AbsoluteFill>
  );
};

export default ExemplarChartScene;
