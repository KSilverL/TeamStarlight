import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { NodeDiagramSlide as NodeDiagramSlideProps } from "../types";

export const NodeDiagramSlide: React.FC<{
  slide: NodeDiagramSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, secondaryColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  // 9:16 stacks the chain top-to-bottom (more vertical room than horizontal);
  // 16:9 lays it out left-to-right.
  const vertical = height > width;

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
      <div
        style={{
          display: "flex",
          flexDirection: vertical ? "column" : "row",
          alignItems: "center",
          gap: vertical ? 28 : 36,
        }}
      >
        {slide.nodes.map((node, i) => {
          const delay = i * 10;
          const enter = spring({ frame: frame - delay, fps, config: { damping: 14 } });
          const opacity = interpolate(frame - delay, [0, 10], [0, 1], {
            extrapolateRight: "clamp",
            extrapolateLeft: "clamp",
          });
          const lineOpacity = interpolate(frame - delay - 6, [0, 10], [0, 1], {
            extrapolateRight: "clamp",
            extrapolateLeft: "clamp",
          });
          const color = i % 2 === 0 ? accentColor : secondaryColor;

          return (
            <React.Fragment key={i}>
              {i > 0 && (
                <div
                  style={{
                    backgroundColor: "rgba(255,255,255,0.3)",
                    opacity: lineOpacity,
                    width: vertical ? 3 : 48,
                    height: vertical ? 48 : 3,
                  }}
                />
              )}
              <div
                style={{
                  opacity,
                  transform: `scale(${enter})`,
                  padding: "18px 28px",
                  borderRadius: 16,
                  backgroundColor: color,
                  color: "white",
                  fontSize: 24,
                  fontWeight: 800,
                  textAlign: "center",
                  minWidth: 120,
                }}
              >
                {node}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
