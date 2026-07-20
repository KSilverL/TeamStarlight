import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import type { BarChartSlide as BarChartSlideProps } from "../types";
import { chartAxisForTheme, chartGridForTheme, textColorForTheme, type Theme } from "./theme";
import { countUp, fadeIn, springEnter, stagger } from "../design/animations";
import { SlideHeadline, SourceCaption } from "../design/components";
import { paletteFor } from "../design/palettes";
import { bodyFont, displayFont } from "../design/fonts";
import { accentGlow, fontSize, radius } from "../design/tokens";

interface BarShapeProps {
  x: number;
  y: number;
  width: number;
  height: number;
  index: number;
}

export const BarChartSlide: React.FC<{
  slide: BarChartSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const variant = slide.variant ?? "columns";
  const textColor = textColorForTheme(theme);
  const palette = paletteFor(slide.paletteName, { accentColor, secondaryColor }, theme);
  const barColor = (i: number) => (slide.highlightIndex === i ? accentColor : palette[i % palette.length]);

  const headline = slide.headline ? <SlideHeadline color={textColor}>{slide.headline}</SlideHeadline> : null;
  const source = slide.source ? <SourceCaption color={textColor}>{slide.source}</SourceCaption> : null;

  // ── race: horizontal bars sorted descending, count-up values, leader glows ──
  if (variant === "race") {
    const ranked = slide.bars
      .map((bar, originalIndex) => ({ ...bar, originalIndex }))
      .sort((a, b) => b.value - a.value);
    const max = Math.max(...ranked.map((b) => b.value)) || 1;
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        {headline}
        <div style={{ width: "82%", display: "flex", flexDirection: "column", gap: 18 }}>
          {ranked.map((bar, i) => {
            const delay = stagger(i, 8);
            const grow = springEnter(frame, fps, { delay, damping: 18 });
            const isLeader = i === 0;
            const color = barColor(bar.originalIndex);
            return (
              <div key={i} style={{ opacity: fadeIn(frame, { delay, frames: 8 }) }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ color: textColor, fontSize: fontSize.caption, fontFamily: bodyFont }}>{bar.label}</span>
                  <span style={{ color: textColor, fontSize: fontSize.label, fontWeight: 800, fontFamily: displayFont }}>
                    {countUp(frame, bar.value, { delay }).toLocaleString()}
                  </span>
                </div>
                <div style={{ height: 28, borderRadius: radius.bar, backgroundColor: chartGridForTheme(theme) }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${(bar.value / max) * 100 * grow}%`,
                      borderRadius: radius.bar,
                      backgroundColor: color,
                      boxShadow: isLeader ? accentGlow(color, 20) : undefined,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        {source}
      </AbsoluteFill>
    );
  }

  // ── lollipop: thin stems with popping circle heads ────────────────────────
  if (variant === "lollipop") {
    const max = Math.max(...slide.bars.map((b) => b.value)) || 1;
    const plotH = height * 0.42;
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        {headline}
        <div style={{ width: "82%", height: plotH, display: "flex", alignItems: "flex-end", justifyContent: "space-around" }}>
          {slide.bars.map((bar, i) => {
            const delay = stagger(i, 7);
            const grow = springEnter(frame, fps, { delay, damping: 16 });
            const h = (bar.value / max) * plotH * grow;
            const color = barColor(i);
            return (
              <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", height: "100%", justifyContent: "flex-end" }}>
                <span style={{ color: textColor, fontSize: fontSize.caption, fontWeight: 800, fontFamily: displayFont, marginBottom: 8, opacity: fadeIn(frame, { delay: delay + 6, frames: 8 }) }}>
                  {bar.value.toLocaleString()}
                </span>
                <div style={{ width: 4, height: Math.max(0, h - 28), backgroundColor: color, opacity: 0.6 }} />
                <div style={{ width: 28, height: 28, borderRadius: "50%", backgroundColor: color, transform: `scale(${grow})` }} />
                <span style={{ color: textColor, fontSize: fontSize.tick, fontFamily: bodyFont, marginTop: 10, opacity: 0.85 }}>{bar.label}</span>
              </div>
            );
          })}
        </div>
        {source}
      </AbsoluteFill>
    );
  }

  // ── columns (default): vertical Recharts bars growing from the baseline ────
  const axisColor = chartAxisForTheme(theme);
  const renderBar = (props: BarShapeProps) => {
    const { x, y, width: barWidth, height: barHeight, index } = props;
    const delay = stagger(index, 6);
    const growth = springEnter(frame, fps, { delay, damping: 16 });
    const drawnHeight = barHeight * growth;
    const color = barColor(index);
    return (
      <rect
        x={x}
        y={y + (barHeight - drawnHeight)}
        width={barWidth}
        height={drawnHeight}
        fill={color}
        opacity={fadeIn(frame, { delay, frames: 8 })}
        rx={radius.bar}
        style={{ filter: slide.highlightIndex === index ? `drop-shadow(${accentGlow(color, 12)})` : undefined }}
      />
    );
  };

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {headline}
      <BarChart width={width * 0.82} height={height * 0.42} data={slide.bars} margin={{ top: 20, right: 20, left: 0, bottom: 10 }}>
        <CartesianGrid stroke={chartGridForTheme(theme)} vertical={false} />
        <XAxis dataKey="label" stroke={axisColor} tick={{ fill: axisColor, fontSize: fontSize.tick }} />
        <YAxis stroke={axisColor} tick={{ fill: axisColor, fontSize: fontSize.tick }} width={50} />
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <Bar dataKey="value" shape={renderBar as any} isAnimationActive={false} />
      </BarChart>
      {source}
    </AbsoluteFill>
  );
};
