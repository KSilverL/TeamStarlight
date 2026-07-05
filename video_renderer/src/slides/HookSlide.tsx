import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { HookSlide as HookSlideProps } from "../types";

const SHAPE_RADIUS: Record<HookSlideProps["shape"], string> = {
  circle: "50%",
  blob: "62% 38% 55% 45% / 45% 60% 40% 55%",
  hex: "10%",
};

export const HookSlide: React.FC<{ slide: HookSlideProps; accentColor: string; primaryColor: string }> = ({
  slide,
  accentColor,
  primaryColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scale = spring({ frame, fps, config: { damping: 14, mass: 0.6 } });
  const headlineOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const headlineY = interpolate(frame, [0, 15], [30, 0], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {slide.imageLocalPath && (
        <div
          style={{
            position: "absolute",
            width: "55%",
            aspectRatio: "1 / 1",
            borderRadius: SHAPE_RADIUS[slide.shape],
            backgroundColor: accentColor,
            transform: `scale(${scale})`,
            overflow: "hidden",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          {/* imageLocalPath is job-directory-relative (e.g. "images/0.png"), served via
              the render's --public-dir; staticFile() resolves it to a loadable URL —
              Chromium's headless renderer refuses file:// resources outright. */}
          <Img src={staticFile(slide.imageLocalPath)} style={{ width: "85%", objectFit: "contain" }} />
        </div>
      )}
      <div
        style={{
          position: "absolute",
          bottom: "12%",
          width: "85%",
          textAlign: "center",
          opacity: headlineOpacity,
          transform: `translateY(${headlineY}px)`,
        }}
      >
        <h1 style={{ color: "white", fontSize: 64, fontWeight: 800, margin: 0, lineHeight: 1.1 }}>
          {slide.headline}
        </h1>
        {slide.subtext && (
          <p style={{ color: "white", opacity: 0.8, fontSize: 28, marginTop: 16 }}>{slide.subtext}</p>
        )}
      </div>
    </AbsoluteFill>
  );
};
