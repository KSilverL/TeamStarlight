import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import type { LineChartSlide as LineChartSlideProps } from "../types";

const LINE_COLORS = ["#f5c84c", "#34c98f", "#e2725b"];

export const LineChartSlide: React.FC<{
  slide: LineChartSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, secondaryColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const chartWidth = width * 0.82;
  const chartHeight = height * 0.4;

  // Same as PieChartSlide: Recharts' own animation isn't frame-deterministic, so the
  // "drawing in" effect comes from revealing one more x-axis point per advancing
  // frame range instead of relying on Line's isAnimationActive.
  const drawFrames = Math.round(slide.durationFrames * 0.6);
  const revealCount = Math.max(
    1,
    Math.round(interpolate(frame, [0, drawFrames], [1, slide.xLabels.length], { extrapolateRight: "clamp" })),
  );
  const badgeOpacity = interpolate(frame, [drawFrames, drawFrames + 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const data = slide.xLabels.slice(0, revealCount).map((x, i) => {
    const point: Record<string, string | number> = { x };
    slide.series.forEach((s) => {
      point[s.label] = s.values[i];
    });
    return point;
  });

  // See PieChartSlide.tsx for why duplicates against the brand colors are filtered.
  const colors = [
    accentColor,
    secondaryColor,
    ...LINE_COLORS.filter(
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
      <LineChart width={chartWidth} height={chartHeight} data={data} margin={{ top: 20, right: 30, left: 0, bottom: 10 }}>
        <CartesianGrid stroke="rgba(255,255,255,0.12)" vertical={false} />
        <XAxis dataKey="x" stroke="rgba(255,255,255,0.6)" tick={{ fill: "rgba(255,255,255,0.6)", fontSize: 16 }} />
        <YAxis stroke="rgba(255,255,255,0.6)" tick={{ fill: "rgba(255,255,255,0.6)", fontSize: 16 }} width={50} />
        {slide.series.map((s, i) => (
          <Line
            key={s.label}
            type="monotone"
            dataKey={s.label}
            stroke={colors[i % colors.length]}
            strokeWidth={4}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
      <div style={{ position: "absolute", bottom: "10%", display: "flex", gap: 24, opacity: badgeOpacity }}>
        {slide.series.map((s, i) => (
          <div
            key={s.label}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 18px",
              borderRadius: 999,
              backgroundColor: "rgba(255,255,255,0.08)",
            }}
          >
            <span style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: colors[i % colors.length] }} />
            <span style={{ color: "white", fontWeight: 700, fontSize: 20 }}>
              {s.label}: {s.values[s.values.length - 1].toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
