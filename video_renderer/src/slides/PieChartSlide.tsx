import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Cell, Pie, PieChart } from "recharts";
import type { PieChartSlide as PieChartSlideProps } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { fadeIn, progress } from "../design/animations";
import { SlideHeadline, SourceCaption } from "../design/components";
import { paletteFor } from "../design/palettes";
import { bodyFont, displayFont } from "../design/fonts";
import { fontSize } from "../design/tokens";

export const PieChartSlide: React.FC<{
  slide: PieChartSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const chartSize = Math.min(width, height) * 0.55;
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "classic";
  const colors = paletteFor(slide.paletteName, { accentColor, secondaryColor }, theme);

  // Recharts' built-in animation (react-smooth) is wall-clock-time-based, not
  // frame-deterministic, so it's disabled everywhere here. The "drawing in" effect
  // comes from interpolating endAngle per rendered frame.
  const drawFrames = Math.round(slide.durationFrames * 0.55);
  const sweep = progress(frame, { to: drawFrames }) * 360;
  const legendOpacity = fadeIn(frame, { frames: 15 });
  const calloutOpacity = fadeIn(frame, { delay: drawFrames, frames: 12 });

  const isDonut = variant === "donut";
  const isExploded = variant === "exploded";
  const innerRadius = isDonut ? chartSize * 0.3 : chartSize * 0.22;

  const legend = (
    <div
      style={{
        position: "absolute",
        bottom: slide.calloutText && !isDonut ? "22%" : "12%",
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
          <span style={{ color: textColor, fontSize: fontSize.caption, fontFamily: bodyFont, opacity: 0.85 }}>{slice.label}</span>
        </div>
      ))}
    </div>
  );

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {slide.headline && <SlideHeadline color={textColor}>{slide.headline}</SlideHeadline>}
      <div style={{ position: "relative", width: chartSize, height: chartSize, display: "flex", justifyContent: "center", alignItems: "center" }}>
        <PieChart width={chartSize} height={chartSize}>
          <Pie
            data={slide.slices}
            dataKey="value"
            nameKey="label"
            cx="50%"
            cy="50%"
            innerRadius={innerRadius}
            outerRadius={chartSize * 0.45}
            startAngle={90}
            endAngle={90 - sweep}
            isAnimationActive={false}
            stroke={isExploded ? primaryColor : "none"}
            strokeWidth={isExploded ? 4 : 0}
          >
            {slide.slices.map((_, i) => (
              <Cell key={i} fill={colors[i % colors.length]} />
            ))}
          </Pie>
        </PieChart>
        {/* donut: the callout number lives big in the hole */}
        {isDonut && slide.calloutText && (
          <div
            style={{
              position: "absolute",
              textAlign: "center",
              opacity: calloutOpacity,
              color: textColor,
              fontSize: fontSize.subhead,
              fontWeight: 800,
              fontFamily: displayFont,
              maxWidth: innerRadius * 1.8,
            }}
          >
            {slide.calloutText}
          </div>
        )}
      </div>
      {legend}
      {/* non-donut callout sits below the chart */}
      {!isDonut && slide.calloutText && (
        <div
          style={{
            position: "absolute",
            bottom: "8%",
            opacity: calloutOpacity,
            color: textColor,
            fontSize: fontSize.subhead,
            fontWeight: 800,
            fontFamily: displayFont,
            textAlign: "center",
          }}
        >
          {slide.calloutText}
        </div>
      )}
      {slide.source && <SourceCaption color={textColor}>{slide.source}</SourceCaption>}
    </AbsoluteFill>
  );
};
