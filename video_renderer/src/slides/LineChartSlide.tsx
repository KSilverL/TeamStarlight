import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import type { LineChartSlide as LineChartSlideProps } from "../types";
import { chartAxisForTheme, chartGridForTheme, surfaceWashForTheme, textColorForTheme, type Theme } from "./theme";
import { fadeIn } from "../design/animations";
import { SlideHeadline, SourceCaption } from "../design/components";
import { paletteFor, withAlpha } from "../design/palettes";
import { bodyFont, displayFont } from "../design/fonts";
import { fontSize, radius } from "../design/tokens";

export const LineChartSlide: React.FC<{
  slide: LineChartSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const chartWidth = width * 0.82;
  const chartHeight = height * 0.4;
  const axisColor = chartAxisForTheme(theme);
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "classic";
  const colors = paletteFor(slide.paletteName, { accentColor, secondaryColor }, theme);

  // Recharts' own animation isn't frame-deterministic, so the "drawing in" effect
  // comes from revealing one more x-axis point per advancing frame range.
  const drawFrames = Math.round(slide.durationFrames * 0.6);
  const revealCount = Math.max(
    1,
    Math.round(interpolate(frame, [0, drawFrames], [1, slide.xLabels.length], { extrapolateRight: "clamp" })),
  );
  const badgeOpacity = fadeIn(frame, { delay: drawFrames, frames: 15 });

  const data = slide.xLabels.slice(0, revealCount).map((x, i) => {
    const point: Record<string, string | number> = { x };
    slide.series.forEach((s) => {
      point[s.label] = s.values[i];
    });
    return point;
  });

  const annotation = slide.annotation ? (
    <div style={{ position: "absolute", top: "20%", right: "8%", opacity: badgeOpacity, textAlign: "right" }}>
      <span style={{ color: accentColor, fontSize: fontSize.label, fontWeight: 800, fontFamily: displayFont }}>{slide.annotation}</span>
    </div>
  ) : null;
  const source = slide.source ? <SourceCaption color={textColor}>{slide.source}</SourceCaption> : null;

  // ── area_glow: single hero series with a glowing gradient fill under it ────
  if (variant === "area_glow") {
    const s = slide.series[0];
    const color = colors[0];
    const areaData = slide.xLabels.slice(0, revealCount).map((x, i) => ({ x, v: s.values[i] }));
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        {slide.headline && <SlideHeadline color={textColor}>{slide.headline}</SlideHeadline>}
        <AreaChart width={chartWidth} height={chartHeight} data={areaData} margin={{ top: 20, right: 30, left: 0, bottom: 10 }}>
          <defs>
            <linearGradient id="area-glow-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.55} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={chartGridForTheme(theme)} vertical={false} />
          <XAxis dataKey="x" stroke={axisColor} tick={{ fill: axisColor, fontSize: fontSize.tick }} />
          <YAxis stroke={axisColor} tick={{ fill: axisColor, fontSize: fontSize.tick }} width={50} />
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={4} fill="url(#area-glow-fill)" isAnimationActive={false} />
        </AreaChart>
        <div style={{ position: "absolute", bottom: "10%", opacity: badgeOpacity }}>
          <span style={{ color: textColor, fontWeight: 700, fontSize: fontSize.body, fontFamily: displayFont }}>
            {s.label}: {s.values[s.values.length - 1].toLocaleString()}
          </span>
        </div>
        {annotation}
        {source}
      </AbsoluteFill>
    );
  }

  // ── step_reveal: a vertical scrubber sweeps across, lighting x-labels ──────
  const showScrubber = variant === "step_reveal";
  const scrubX = showScrubber
    ? interpolate(frame, [0, drawFrames], [0, chartWidth], { extrapolateRight: "clamp" })
    : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {slide.headline && <SlideHeadline color={textColor}>{slide.headline}</SlideHeadline>}
      <div style={{ position: "relative" }}>
        <LineChart width={chartWidth} height={chartHeight} data={data} margin={{ top: 20, right: 30, left: 0, bottom: 10 }}>
          <CartesianGrid stroke={chartGridForTheme(theme)} vertical={false} />
          <XAxis dataKey="x" stroke={axisColor} tick={{ fill: axisColor, fontSize: fontSize.tick }} />
          <YAxis stroke={axisColor} tick={{ fill: axisColor, fontSize: fontSize.tick }} width={50} />
          {slide.series.map((s, i) => (
            <Line key={s.label} type="monotone" dataKey={s.label} stroke={colors[i % colors.length]} strokeWidth={4} dot={false} isAnimationActive={false} />
          ))}
        </LineChart>
        {showScrubber && (
          <div style={{ position: "absolute", top: 20, left: scrubX, width: 2, height: chartHeight - 30, backgroundColor: withAlpha(accentColor, 0.7) }} />
        )}
      </div>
      <div style={{ position: "absolute", bottom: "10%", display: "flex", gap: 24, opacity: badgeOpacity }}>
        {slide.series.map((s, i) => (
          <div
            key={s.label}
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 18px", borderRadius: radius.pill, backgroundColor: surfaceWashForTheme(theme) }}
          >
            <span style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: colors[i % colors.length] }} />
            <span style={{ color: textColor, fontWeight: 700, fontSize: fontSize.caption, fontFamily: bodyFont }}>
              {s.label}: {s.values[s.values.length - 1].toLocaleString()}
            </span>
          </div>
        ))}
      </div>
      {annotation}
      {source}
    </AbsoluteFill>
  );
};
