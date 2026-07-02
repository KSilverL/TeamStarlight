import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { OutroSlide as OutroSlideProps } from "../types";

export const OutroSlide: React.FC<{ slide: OutroSlideProps; accentColor: string; primaryColor: string }> = ({
  slide,
  accentColor,
  primaryColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const buttonScale = spring({ frame: frame - 10, fps, config: { damping: 12 } });
  const fade = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      <div style={{ opacity: fade, textAlign: "center" }}>
        <h1 style={{ color: "white", fontSize: 52, fontWeight: 900, letterSpacing: 2, margin: 0 }}>
          {slide.brandName}
        </h1>
        <div
          style={{
            marginTop: 36,
            display: "inline-block",
            padding: "16px 40px",
            borderRadius: 999,
            backgroundColor: accentColor,
            color: "white",
            fontSize: 26,
            fontWeight: 700,
            transform: `scale(${buttonScale})`,
          }}
        >
          {slide.ctaLabel}
        </div>
        {slide.contact && (
          <p style={{ color: "white", opacity: 0.7, fontSize: 20, marginTop: 24 }}>{slide.contact}</p>
        )}
      </div>
    </AbsoluteFill>
  );
};
