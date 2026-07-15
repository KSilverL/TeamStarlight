// Decorative background layers, rendered UNDER a slide's content inside its
// AbsoluteFill. All are pure functions of frame (drift, never wall-clock) and the
// brand colours, kept low-contrast so foreground text always stays legible.

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { withAlpha } from "./palettes";

/** Static diagonal wash from secondary→accent over the primary background. */
export const GradientWash: React.FC<{
  accentColor: string;
  secondaryColor: string;
  /** 0..1 — how visible the wash is over the primary background. */
  strength?: number;
  angle?: number;
}> = ({ accentColor, secondaryColor, strength = 0.22, angle = 135 }) => (
  <AbsoluteFill
    style={{
      background: `linear-gradient(${angle}deg, ${withAlpha(secondaryColor, strength)} 0%, transparent 45%, ${withAlpha(accentColor, strength)} 100%)`,
    }}
  />
);

/** 2-3 giant blurred brand-colour orbs, drifting slowly — the "aurora" look. */
export const BackdropOrbs: React.FC<{
  accentColor: string;
  secondaryColor: string;
  count?: 2 | 3;
  opacity?: number;
}> = ({ accentColor, secondaryColor, count = 3, opacity = 0.3 }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const orbs = [
    { color: accentColor, cx: 0.2, cy: 0.25, r: 0.42, speed: 0.6, phase: 0 },
    { color: secondaryColor, cx: 0.82, cy: 0.7, r: 0.5, speed: 0.45, phase: 2.1 },
    { color: accentColor, cx: 0.65, cy: 0.12, r: 0.34, speed: 0.7, phase: 4.2 },
  ].slice(0, count);
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      {orbs.map((orb, i) => {
        // Slow Lissajous drift — a few dozen px over a whole slide, felt not seen.
        const t = (frame * orb.speed) / 60 + orb.phase;
        const dx = Math.sin(t) * width * 0.03;
        const dy = Math.cos(t * 0.8) * height * 0.02;
        const size = Math.min(width, height) * orb.r;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: orb.cx * width - size / 2 + dx,
              top: orb.cy * height - size / 2 + dy,
              width: size,
              height: size,
              borderRadius: "50%",
              backgroundColor: orb.color,
              opacity,
              filter: `blur(${size * 0.35}px)`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/** Faint line grid — technical/data moods. */
export const GridPattern: React.FC<{
  color: string;
  cell?: number;
  opacity?: number;
}> = ({ color, cell = 72, opacity = 0.1 }) => (
  <AbsoluteFill
    style={{
      opacity,
      backgroundImage: `linear-gradient(${color} 1px, transparent 1px), linear-gradient(90deg, ${color} 1px, transparent 1px)`,
      backgroundSize: `${cell}px ${cell}px`,
    }}
  />
);

/** Film-grain noise overlay (SVG feTurbulence) — depth without banding. */
export const NoiseTexture: React.FC<{ opacity?: number }> = ({ opacity = 0.05 }) => (
  <AbsoluteFill style={{ opacity, mixBlendMode: "overlay" }}>
    <svg width="100%" height="100%">
      <filter id="design-noise">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
      </filter>
      <rect width="100%" height="100%" filter="url(#design-noise)" />
    </svg>
  </AbsoluteFill>
);
