import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import type { BarChartSlide as BarChartSlideProps } from "../types";

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
  primaryColor: string;
}> = ({ slide, accentColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const chartWidth = width * 0.82;
  const chartHeight = height * 0.42;

  // Recharts can't be driven by Remotion's per-frame progress through its own
  // animation system (time-based, not frame-deterministic) — a custom `shape`
  // renderer lets each bar grow from its own baseline using values computed fresh
  // for the exact frame being rendered, staggered like CounterStatSlide's cards.
  const renderBar = (props: BarShapeProps) => {
    const { x, y, width: barWidth, height: barHeight, index } = props;
    const delay = index * 6;
    const growth = spring({ frame: frame - delay, fps, config: { damping: 16 } });
    const drawnHeight = barHeight * growth;
    const opacity = interpolate(frame - delay, [0, 8], [0, 1], {
      extrapolateRight: "clamp",
      extrapolateLeft: "clamp",
    });
    return (
      <rect
        x={x}
        y={y + (barHeight - drawnHeight)}
        width={barWidth}
        height={drawnHeight}
        fill={accentColor}
        opacity={opacity}
        rx={6}
      />
    );
  };

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
      <BarChart width={chartWidth} height={chartHeight} data={slide.bars} margin={{ top: 20, right: 20, left: 0, bottom: 10 }}>
        <CartesianGrid stroke="rgba(255,255,255,0.12)" vertical={false} />
        <XAxis dataKey="label" stroke="rgba(255,255,255,0.6)" tick={{ fill: "rgba(255,255,255,0.6)", fontSize: 16 }} />
        <YAxis stroke="rgba(255,255,255,0.6)" tick={{ fill: "rgba(255,255,255,0.6)", fontSize: 16 }} width={50} />
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <Bar dataKey="value" shape={renderBar as any} isAnimationActive={false} />
      </BarChart>
    </AbsoluteFill>
  );
};
