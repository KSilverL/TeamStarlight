// Shared slide sub-components — the blocks that were copy-pasted (with drifting
// constants) across the slide files: the absolute-positioned headline h2, the CTA
// pill, plus small new blocks (Kicker, SourceCaption) for the variant rollout.

import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { springEnter } from "./animations";
import { displayFont, bodyFont } from "./fonts";
import { fontSize, letterSpacing, radius } from "./tokens";

/**
 * The standard slide headline: absolutely positioned across the top, centred —
 * the exact h2 block 7 slide files used to duplicate. `top` matches each caller's
 * original offset (6% for charts/diagrams, 4% for collage).
 */
export const SlideHeadline: React.FC<{
  children: React.ReactNode;
  color: string;
  top?: string;
  size?: number;
  opacity?: number;
}> = ({ children, color, top = "6%", size = fontSize.headline, opacity = 1 }) => (
  <h2
    style={{
      position: "absolute",
      top,
      width: "100%",
      textAlign: "center",
      color,
      fontSize: size,
      fontWeight: 800,
      fontFamily: displayFont,
      margin: 0,
      opacity,
    }}
  >
    {children}
  </h2>
);

/** Small ALL-CAPS eyebrow line above a headline. */
export const Kicker: React.FC<{ children: React.ReactNode; color: string }> = ({ children, color }) => (
  <div
    style={{
      color,
      fontSize: fontSize.caption,
      fontWeight: 700,
      fontFamily: bodyFont,
      letterSpacing: letterSpacing.caps,
      textTransform: "uppercase",
      opacity: 0.9,
    }}
  >
    {children}
  </div>
);

/** Right-aligned attribution line for charts ("Source: ..."). */
export const SourceCaption: React.FC<{ children: React.ReactNode; color: string }> = ({ children, color }) => (
  <div
    style={{
      position: "absolute",
      bottom: "4%",
      right: "6%",
      color,
      opacity: 0.55,
      fontSize: fontSize.tick,
      fontFamily: bodyFont,
    }}
  >
    {children}
  </div>
);

/** The outro's spring-in CTA pill, reusable by any variant that needs a button. */
export const CtaButton: React.FC<{
  children: React.ReactNode;
  backgroundColor: string;
  color: string;
  delay?: number;
}> = ({ children, backgroundColor, color, delay = 10 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = springEnter(frame, fps, { delay, damping: 12 });
  return (
    <div
      style={{
        display: "inline-block",
        padding: "16px 40px",
        borderRadius: radius.pill,
        backgroundColor,
        color,
        fontSize: 26,
        fontWeight: 700,
        fontFamily: displayFont,
        transform: `scale(${scale})`,
      }}
    >
      {children}
    </div>
  );
};
