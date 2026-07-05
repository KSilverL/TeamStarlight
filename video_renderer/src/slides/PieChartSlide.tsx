import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Cell, Pie, PieChart } from "recharts";
import type { PieChartSlide as PieChartSlideProps } from "../types";

const SLICE_COLORS = ["#f5c84c", "#2d4ed8", "#e2725b", "#34c98f", "#a06cd5", "#ff8966"];

export const PieChartSlide: React.FC<{
  slide: PieChartSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, secondaryColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const chartSize = Math.min(width, height) * 0.55;

  // Recharts' built-in animation (react-smooth) is wall-clock-time-based, not
  // frame-deterministic, so it's disabled (isAnimationActive=false) everywhere here.
  // The "drawing in" effect instead comes from interpolating endAngle per rendered
  // frame, which Remotion can capture identically on every render pass.
  const drawFrames = Math.round(slide.durationFrames * 0.55);
  const sweep = interpolate(frame, [0, drawFrames], [0, 360], { extrapolateRight: "clamp" });
  const legendOpacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  const calloutOpacity = interpolate(frame, [drawFrames, drawFrames + 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Brand colors take priority, but a brand's accent/secondary can coincidentally
  // match an entry in the fallback palette (e.g. both happen to be "#f5c84c") —
  // filtering duplicates out keeps every slice visually distinct regardless.
  const colors = [
    accentColor,
    secondaryColor,
    ...SLICE_COLORS.filter(
      (c) => c.toLowerCase() !== accentColor.toLowerCase() && c.toLowerCase() !== secondaryColor.toLowerCase(),
    ),
  ];

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {slide.headline && (
        <h2
          style={{
            position: "absolute",
            top: "6%",
            width: "100%",
            textAlign: "center",
            color: "white",
            fontSize: 40,
            fontWeight: 800,
          }}
        >
          {slide.headline}
        </h2>
      )}
      <PieChart width={chartSize} height={chartSize}>
        <Pie
          data={slide.slices}
          dataKey="value"
          nameKey="label"
          cx="50%"
          cy="50%"
          innerRadius={chartSize * 0.22}
          outerRadius={chartSize * 0.45}
          startAngle={90}
          endAngle={90 - sweep}
          isAnimationActive={false}
          stroke="none"
        >
          {slide.slices.map((_, i) => (
            <Cell key={i} fill={colors[i % colors.length]} />
          ))}
        </Pie>
      </PieChart>
      <div
        style={{
          position: "absolute",
          bottom: slide.calloutText ? "22%" : "12%",
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: 16,
          width: "80%",
          opacity: legendOpacity,
        }}
      >
        {slide.slices.map((slice, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: colors[i % colors.length] }} />
            <span style={{ color: "white", fontSize: 18, opacity: 0.85 }}>{slice.label}</span>
          </div>
        ))}
      </div>
      {slide.calloutText && (
        <div
          style={{
            position: "absolute",
            bottom: "8%",
            opacity: calloutOpacity,
            color: "white",
            fontSize: 32,
            fontWeight: 800,
            textAlign: "center",
          }}
        >
          {slide.calloutText}
        </div>
      )}
    </AbsoluteFill>
  );
};
