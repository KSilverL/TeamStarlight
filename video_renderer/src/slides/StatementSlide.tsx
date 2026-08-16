import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { StatementSlide as StatementSlideProps } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { kenBurns, riseSoft } from "../design/animations";
import { PixelMosaic } from "../design/backdrops";
import { Kicker, WordReveal } from "../design/components";
import { fontSize } from "../design/tokens";

// Text-block geometry, measured off the reference video and expressed as
// percentages so it holds at 9:16, 16:9 and 1:1 alike.
//
// left/right are deliberately ASYMMETRIC: the extra right inset forces line breaks
// a little earlier, so the ragged right edge reads as a designed rag rather than as
// text that happened to run out of room.
const TEXT_LEFT = "10%";
const TEXT_RIGHT = "12%";

// The block is centred VERTICALLY and then nudged up, rather than pinned to a fixed
// top offset: a statement can be one line or four, and a fixed top makes the short
// ones float and the long ones sink. Centring keeps both balanced; the -6% bias is
// the reference's "slightly off centre" placement.
const VERTICAL_BIAS = "-6%";

export const StatementSlide: React.FC<{
  slide: StatementSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { height } = useVideoConfig();
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "mosaic";

  // The whole block creeps toward the viewer over the slide — the emphasis move
  // from the reference. transformOrigin pins the left inset so the margin holds
  // steady while the type grows.
  const blockZoom = kenBurns(frame, slide.durationFrames, { from: 1, to: 1.035 });

  const mosaic = (
    <PixelMosaic
      primaryColor={primaryColor}
      secondaryColor={secondaryColor}
      accentColor={accentColor}
      contrast={0.85}
    />
  );

  // Flex is safe HERE (it only centres the column); WordReveal's own inner
  // container must stay a plain block or the browser loses its wrapping points.
  const body = (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "flex-start",
        flexDirection: "column",
        paddingLeft: TEXT_LEFT,
        paddingRight: TEXT_RIGHT,
        transform: `translateY(${VERTICAL_BIAS})`,
      }}
    >
      {slide.kicker && (
        <div style={{ marginBottom: 18, ...riseSoft(frame, { delay: 2, distance: 16 }) }}>
          <Kicker color={accentColor}>{slide.kicker}</Kicker>
        </div>
      )}
      <div style={{ width: "100%", transform: blockZoom, transformOrigin: "0% 50%" }}>
        <WordReveal
          text={slide.text}
          color={textColor}
          emphasisColor={accentColor}
          emphasis={slide.emphasisWords}
          durationFrames={slide.durationFrames}
          startDelay={slide.kicker ? 6 : 0}
        />
      </div>
    </AbsoluteFill>
  );

  // ── band: mosaic across the top, text below on the flat background ─────────
  // A middle register between the full field and nothing — the mosaic still sets
  // the mood but the type sits on plain colour, so it can run smaller and longer.
  if (variant === "band") {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        <AbsoluteFill style={{ height: "46%", overflow: "hidden" }}>{mosaic}</AbsoluteFill>
        {slide.kicker && (
          <div style={{ position: "absolute", top: "53%", left: TEXT_LEFT, right: TEXT_RIGHT }}>
            <Kicker color={accentColor}>{slide.kicker}</Kicker>
          </div>
        )}
        <div
          style={{
            position: "absolute",
            top: "59%",
            left: TEXT_LEFT,
            right: TEXT_RIGHT,
            transform: blockZoom,
            transformOrigin: "0% 50%",
          }}
        >
          <WordReveal
            text={slide.text}
            color={textColor}
            emphasisColor={accentColor}
            emphasis={slide.emphasisWords}
            fontSize={height > 1200 ? fontSize.h1 : fontSize.title}
            durationFrames={slide.durationFrames}
            startDelay={slide.kicker ? 6 : 0}
          />
        </div>
      </AbsoluteFill>
    );
  }

  // ── flat: no mosaic — a quiet beat, and the degradation target ─────────────
  if (variant === "flat") {
    return <AbsoluteFill style={{ backgroundColor: primaryColor }}>{body}</AbsoluteFill>;
  }

  // ── mosaic (default): the full field behind the type ───────────────────────
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {mosaic}
      {body}
    </AbsoluteFill>
  );
};
