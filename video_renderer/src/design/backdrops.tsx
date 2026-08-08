// Decorative background layers, rendered UNDER a slide's content inside its
// AbsoluteFill. All are pure functions of frame (drift, never wall-clock) and the
// brand colours, kept low-contrast so foreground text always stays legible.

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import {
  cellAlpha,
  hashUnit,
  isDrawableGrid,
  mosaicGrid,
  mosaicRamp,
  mosaicShade,
  rampColor,
} from "./mosaic";
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

/**
 * Coarse grid of squares, all in the brand's hue family at different lightnesses,
 * undulating slowly — the signature backdrop of the statement/media_statement
 * slides. Unlike the other backdrops in this file it is OPAQUE by default: it is
 * the slide's background, not a wash layered over one.
 *
 * All the maths lives in ./mosaic.ts (pure, unit-tested); this is the JSX shell.
 *
 * Drawn as absolutely-positioned divs rather than a <canvas>: canvas painting in
 * Remotion needs an effect plus delayRender/continueRender to be capture-safe,
 * whereas ~70 divs are frame-pure with no lifecycle at all. isDrawableGrid caps
 * the node count so a hand-written fixture can't ask for thousands.
 */
export const PixelMosaic: React.FC<{
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  /** Cells along the frame's short edge. 6 matches the reference. */
  cellsAcrossShortEdge?: number;
  /** 0..1 — how far the ramp spans from brand colour to primaryColor. Legibility knob. */
  contrast?: number;
  /**
   * Blur radius as a fraction of the cell size — the soft cell edges. Small: the
   * reference's cell boundaries are still clearly boundaries, just not hairlines.
   * Anything past ~0.08 dissolves the grid into a plain gradient.
   */
  softness?: number;
  noiseScale?: number;
  speedFrames?: number;
  seed?: number;
  opacity?: number;
  /** 0 = fully painted, 1 = fully dissolved. Cells drop out in hash order. */
  dissolve?: number;
  dissolveFeather?: number;
  /**
   * Overrides useCurrentFrame() as the noise clock. Required by the mosaic
   * transition: useCurrentFrame() is sequence-local, so the outgoing and incoming
   * slides see completely different frames and would paint different colour fields
   * — the handover between them would read as a jump-cut. Both sides pass the same
   * transition-local frame here so their mosaics are bit-identical at the swap.
   */
  noiseFrame?: number;
}> = ({
  primaryColor,
  secondaryColor,
  accentColor,
  cellsAcrossShortEdge = 6,
  contrast = 0.85,
  softness = 0.05,
  noiseScale,
  speedFrames,
  seed = 0,
  opacity = 1,
  dissolve = 0,
  dissolveFeather = 0.18,
  noiseFrame,
}) => {
  const currentFrame = useCurrentFrame();
  const frame = noiseFrame ?? currentFrame;
  const { width, height } = useVideoConfig();
  const grid = mosaicGrid(width, height, cellsAcrossShortEdge);
  const ramp = mosaicRamp(primaryColor, secondaryColor, accentColor, contrast);
  if (!isDrawableGrid(grid)) return <AbsoluteFill style={{ backgroundColor: primaryColor }} />;

  // The grid is drawn at RENDER_CELL px per cell and then CSS-scaled up to fill the
  // frame, rather than drawn at full size.
  //
  // This is purely a cost decision, and a large one. `filter: blur()` scales with
  // the PIXEL AREA it covers, and a full-frame blur measured as ~60% of this
  // component's render time (a 150-frame mosaic slide: 83s with the blur, 32s
  // without). Blurring a 24px-per-cell surface instead of a 180px-per-cell one is
  // ~56x less area for an identical result, because the blur radius is expressed in
  // the same small units and the upscale magnifies it back. Chromium's bilinear
  // filtering on the upscale also contributes to the soft edge for free.
  const RENDER_CELL = 24;
  const scale = grid.cell / RENDER_CELL;

  const cells: React.ReactNode[] = [];
  // One cell of bleed on every side. The blur would otherwise feather the frame's
  // own edges into transparency; overdrawing past them keeps it working on real
  // colour. (A scale(1.06) would also cover the edges but would misalign the grid
  // against the dissolve's per-cell thresholds.)
  for (let row = -1; row <= grid.rows; row++) {
    for (let col = -1; col <= grid.cols; col++) {
      const shade = mosaicShade(col, row, frame, { noiseScale, speedFrames, seed });
      const alpha = dissolve > 0 ? cellAlpha(hashUnit(col, row, 0, seed), dissolve, dissolveFeather) : 1;
      if (alpha <= 0) continue;
      cells.push(
        <div
          key={`${col}:${row}`}
          style={{
            position: "absolute",
            left: col * RENDER_CELL,
            top: row * RENDER_CELL,
            // +1px: neighbouring cells must overlap slightly or sub-pixel rounding
            // leaves hairline seams the blur then smears into visible gridlines.
            width: RENDER_CELL + 1,
            height: RENDER_CELL + 1,
            backgroundColor: rampColor(shade, ramp),
            opacity: alpha,
          }}
        />,
      );
    }
  }

  return (
    <AbsoluteFill style={{ overflow: "hidden", opacity }}>
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          // Pre-scale dimensions, so the layer still covers the frame afterwards.
          width: width / scale,
          height: height / scale,
          transform: `scale(${scale})`,
          transformOrigin: "0 0",
          // Radius in RENDER_CELL units — the upscale restores it to the same
          // visual softness as `grid.cell * softness` at full size.
          filter: `blur(${RENDER_CELL * softness}px)`,
        }}
      >
        {cells}
      </div>
    </AbsoluteFill>
  );
};

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
