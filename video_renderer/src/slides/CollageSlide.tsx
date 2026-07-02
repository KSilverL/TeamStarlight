import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { CollageSlide as CollageSlideProps } from "../types";

// Slot positions per layout, as % of the frame. A slot with no resolved image
// (Pexels miss / Remove.bg failure that still dropped the whole image) renders
// as a plain colour shape instead of leaving a hole in the composition.
const LAYOUT_SLOTS: Record<CollageSlideProps["layout"], Array<{ top: string; left: string; size: string }>> = {
  grid: [
    { top: "10%", left: "8%", size: "38%" },
    { top: "10%", left: "54%", size: "38%" },
    { top: "52%", left: "8%", size: "38%" },
    { top: "52%", left: "54%", size: "38%" },
  ],
  scatter: [
    { top: "6%", left: "12%", size: "34%" },
    { top: "18%", left: "52%", size: "30%" },
    { top: "55%", left: "10%", size: "32%" },
    { top: "48%", left: "56%", size: "36%" },
  ],
  stack: [
    { top: "8%", left: "20%", size: "60%" },
    { top: "20%", left: "28%", size: "50%" },
    { top: "32%", left: "36%", size: "40%" },
  ],
};

const SHAPE_COLORS = ["#f5c84c", "#2d4ed8", "#e2725b"];

export const CollageSlide: React.FC<{ slide: CollageSlideProps; accentColor: string; secondaryColor: string; primaryColor: string }> = ({
  slide,
  accentColor,
  secondaryColor,
  primaryColor,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const slots = LAYOUT_SLOTS[slide.layout];
  const images = slide.resolvedImages.slice(0, slots.length);

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {slide.headline && (
        <h2
          style={{
            position: "absolute",
            top: "4%",
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
      {slots.map((slot, i) => {
        const image = images[i];
        const delay = i * 6;
        const enter = spring({ frame: frame - delay, fps, config: { damping: 15 } });
        const opacity = interpolate(frame - delay, [0, 10], [0, 1], {
          extrapolateRight: "clamp",
          extrapolateLeft: "clamp",
        });
        const color = i % 2 === 0 ? accentColor : secondaryColor || SHAPE_COLORS[i % SHAPE_COLORS.length];

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              top: slot.top,
              left: slot.left,
              width: slot.size,
              aspectRatio: "1 / 1",
              borderRadius: "50%",
              backgroundColor: color,
              opacity,
              transform: `scale(${enter})`,
              overflow: "hidden",
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
            }}
          >
            {/* localPath is job-directory-relative; see HookSlide.tsx for why staticFile() is required. */}
            {image?.localPath && <Img src={staticFile(image.localPath)} style={{ width: "82%", objectFit: "contain" }} />}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
