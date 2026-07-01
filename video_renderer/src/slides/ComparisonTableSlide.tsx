import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { ComparisonTableSlide as ComparisonTableSlideProps } from "../types";

export const ComparisonTableSlide: React.FC<{
  slide: ComparisonTableSlideProps;
  accentColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const columnTemplate = `1.4fr repeat(${slide.columns.length}, 1fr)`;

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
      <div style={{ width: "84%", display: "grid", gridTemplateColumns: columnTemplate, rowGap: 14, columnGap: 10 }}>
        <div />
        {slide.columns.map((col, i) => (
          <div key={i} style={{ color: "white", opacity: 0.7, fontSize: 18, fontWeight: 700, textAlign: "center" }}>
            {col}
          </div>
        ))}

        {slide.rows.map((row, rIdx) => {
          // Rows reveal one at a time, sliding in from the right, like PropLens'
          // staggered comparison rows.
          const delay = rIdx * 12;
          const enter = spring({ frame: frame - delay, fps, config: { damping: 16 } });
          const opacity = interpolate(frame - delay, [0, 10], [0, 1], {
            extrapolateRight: "clamp",
            extrapolateLeft: "clamp",
          });
          const rowStyle: React.CSSProperties = {
            opacity,
            transform: `translateX(${(1 - enter) * 40}px)`,
          };

          return (
            <React.Fragment key={rIdx}>
              <div
                style={{
                  ...rowStyle,
                  color: "white",
                  fontWeight: 800,
                  fontSize: 22,
                  padding: "14px 16px",
                  borderRadius: 12,
                  backgroundColor: "rgba(255,255,255,0.06)",
                  borderLeft: `4px solid ${accentColor}`,
                }}
              >
                {row.label}
              </div>
              {row.values.map((value, cIdx) => (
                <div
                  key={cIdx}
                  style={{
                    ...rowStyle,
                    color: "white",
                    fontSize: 20,
                    textAlign: "center",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {value}
                </div>
              ))}
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
