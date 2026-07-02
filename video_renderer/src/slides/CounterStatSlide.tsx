import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { CounterStatSlide as CounterStatSlideProps } from "../types";

const StatCard: React.FC<{ value: string; label: string; icon: string; index: number; accentColor: string }> = ({
  value,
  label,
  icon,
  index,
  accentColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const delay = index * 8;
  const enter = spring({ frame: frame - delay, fps, config: { damping: 16 } });
  const opacity = interpolate(frame - delay, [0, 10], [0, 1], { extrapolateRight: "clamp", extrapolateLeft: "clamp" });

  // Numeric stats count up; non-numeric values (e.g. "99%", "10K+") fade in as-is.
  const numeric = Number(value.replace(/[^0-9.]/g, ""));
  const isPureNumber = !Number.isNaN(numeric) && /^[0-9.,]+$/.test(value.trim());
  const displayValue = isPureNumber
    ? Math.round(interpolate(frame - delay, [0, 30], [0, numeric], { extrapolateRight: "clamp", extrapolateLeft: "clamp" })).toLocaleString()
    : value;

  return (
    <div
      style={{
        opacity,
        transform: `translateX(${(1 - enter) * 60}px)`,
        display: "flex",
        alignItems: "center",
        gap: 20,
        padding: "20px 28px",
        borderRadius: 18,
        backgroundColor: "rgba(255,255,255,0.06)",
        borderLeft: `4px solid ${accentColor}`,
      }}
    >
      <span style={{ fontSize: 36 }}>{icon}</span>
      <div>
        <div style={{ color: "white", fontSize: 44, fontWeight: 800 }}>{displayValue}</div>
        <div style={{ color: "white", opacity: 0.7, fontSize: 20 }}>{label}</div>
      </div>
    </div>
  );
};

export const CounterStatSlide: React.FC<{ slide: CounterStatSlideProps; accentColor: string; primaryColor: string }> = ({
  slide,
  accentColor,
  primaryColor,
}) => {
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 24, width: "80%" }}>
        {slide.sectionLabel && (
          <h2 style={{ color: "white", opacity: 0.85, fontSize: 28, marginBottom: 8 }}>{slide.sectionLabel}</h2>
        )}
        {slide.stats.map((stat, i) => (
          <StatCard key={i} index={i} accentColor={accentColor} {...stat} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
