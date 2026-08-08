import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { MediaStatementSlide as MediaStatementSlideProps } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { kenBurns, progress, riseSoft } from "../design/animations";
import { PixelMosaic } from "../design/backdrops";
import { Kicker, WordReveal } from "../design/components";
import { withAlpha } from "../design/palettes";
import { fontSize } from "../design/tokens";

// Geometry measured off the reference video, as percentages so it holds at every
// aspect ratio the pipeline produces. The card's 108% height is deliberate: it
// overflows the bottom edge, which is the "bleeds off frame" look.
const TEXT_LEFT = "10%";
const TEXT_RIGHT = "12%";
const CARD_LEFT = "5.5%";
const CARD_WIDTH = "89%";
const CARD_TOP = "46%";
const CARD_HEIGHT = "62%";

export const MediaStatementSlide: React.FC<{
  slide: MediaStatementSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "inset_card";
  const hasClip = Boolean(slide.mediaLocalPath);
  const duration = slide.durationFrames;

  const mosaic = (
    <PixelMosaic
      primaryColor={primaryColor}
      secondaryColor={secondaryColor}
      accentColor={accentColor}
      contrast={0.85}
    />
  );

  const statement = (opts: { top?: string; centred?: boolean } = {}) => (
    <div
      style={{
        position: "absolute",
        top: opts.top ?? "13%",
        left: TEXT_LEFT,
        right: TEXT_RIGHT,
      }}
    >
      {slide.kicker && (
        <div style={{ marginBottom: 16, ...riseSoft(frame, { delay: 2, distance: 16 }) }}>
          <Kicker color={accentColor}>{slide.kicker}</Kicker>
        </div>
      )}
      <div
        style={{
          transform: kenBurns(frame, duration, { from: 1, to: 1.03 }),
          transformOrigin: "0% 50%",
        }}
      >
        <WordReveal
          text={slide.text}
          color={textColor}
          emphasisColor={accentColor}
          emphasis={slide.emphasisWords}
          fontSize={fontSize.h1}
          durationFrames={duration}
          startDelay={slide.kicker ? 6 : 0}
        />
      </div>
    </div>
  );

  /**
   * The clip, wrapped for a slow zoom.
   *
   * A clip shorter than its slide is SLOWED to fit rather than looped.
   * `<OffthreadVideo>` has no `loop` prop in Remotion 4, and the documented
   * alternative — wrapping it in `<Loop>` — made the compositor fail with
   * "No frame found at position N" on positions it served fine without the wrapper
   * (same file, same frame, passes un-looped and fails looped). Stretching
   * sidesteps that entirely and has no wrap seam, which for ambient B-roll looks
   * better anyway.
   *
   * The slowdown is bounded by PexelsVideoSearch's _CLIP_MIN_DURATION_S = 4s
   * against media_statement's 210-frame (7s) ceiling — so at worst ~0.57x. In
   * practice most stock clips are longer than their slide and play at 1x.
   *
   * mediaDurationFrames rides in from Python because the renderer cannot measure
   * the file: @remotion/media-utils isn't a dependency, and probing at render time
   * would mean IO inside a frame render.
   *
   * `muted`: stock clips carry their own audio, which would fight the narration.
   */
  const clip = (zoomTo: number) => {
    // Stop CLIP_TAIL_MARGIN frames short of the file's end: mediaDurationFrames is
    // derived from a provider-reported float duration, so it can be a frame
    // optimistic, and running the decoder off the end of a clip is the one request
    // guaranteed to fail. Two frames is imperceptible.
    const CLIP_TAIL_MARGIN = 2;
    const clipFrames = slide.mediaDurationFrames
      ? Math.max(1, slide.mediaDurationFrames - CLIP_TAIL_MARGIN)
      : null;
    const playbackRate =
      clipFrames && clipFrames < duration ? Math.max(0.1, clipFrames / duration) : 1;
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          overflow: "hidden",
          transform: kenBurns(frame, duration, { from: 1, to: zoomTo }),
        }}
      >
        <OffthreadVideo
          src={staticFile(slide.mediaLocalPath as string)}
          muted
          playbackRate={playbackRate}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </div>
    );
  };

  // No clip resolved (search miss, download failure, or the Lambda backend) —
  // degrade to the `statement` look rather than leaving a hole. Same contract as
  // ResolvedImage(localPath=None) degrading a collage slot to a plain shape.
  if (!hasClip) {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        {mosaic}
        {statement({ top: "34%" })}
      </AbsoluteFill>
    );
  }

  // ── full_bleed: footage fills the frame, text over it ──────────────────────
  if (variant === "full_bleed") {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        <AbsoluteFill>{clip(1.1)}</AbsoluteFill>
        {/* Without a scrim, near-black text over arbitrary footage is a coin flip. */}
        <AbsoluteFill
          style={{
            background: `linear-gradient(180deg, ${withAlpha(primaryColor, 0.78)} 0%, ${withAlpha(
              primaryColor,
              0.28,
            )} 42%, transparent 62%)`,
          }}
        />
        {statement({ top: "13%" })}
      </AbsoluteFill>
    );
  }

  // ── mosaic_reveal: the mosaic scatters away to uncover the footage, then
  // re-forms before the cut. Self-contained, so it works even at transition:"none".
  if (variant === "mosaic_reveal") {
    const revealIn = progress(frame, { from: 6, to: 28 });
    const refillOut = 1 - progress(frame, { from: duration - 30, to: duration - 8 });
    const dissolve = Math.min(revealIn, refillOut);
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        <AbsoluteFill>{clip(1.1)}</AbsoluteFill>
        <PixelMosaic
          primaryColor={primaryColor}
          secondaryColor={secondaryColor}
          accentColor={accentColor}
          contrast={0.85}
          dissolve={dissolve}
        />
        <AbsoluteFill
          style={{
            background: `linear-gradient(180deg, ${withAlpha(primaryColor, 0.7)} 0%, transparent 55%)`,
          }}
        />
        {statement({ top: "13%" })}
      </AbsoluteFill>
    );
  }

  // ── inset_card (default): text above, footage in a rounded card that bleeds
  // off the bottom edge.
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {mosaic}
      {statement({ top: "13%" })}
      <div
        style={{
          position: "absolute",
          left: CARD_LEFT,
          width: CARD_WIDTH,
          top: CARD_TOP,
          height: CARD_HEIGHT,
          // A COMPUTED px radius, not "2.8%": a percentage border-radius on a
          // non-square box resolves per-axis and skews the corners into ellipses.
          borderRadius: Math.round(width * 0.028),
          overflow: "hidden",
          boxShadow: `0 24px 64px ${withAlpha(textColorForTheme(theme), 0.14)}`,
          ...riseSoft(frame, { delay: 10, distance: 40, fadeFrames: 14, riseFrames: 20 }),
        }}
      >
        {clip(1.12)}
      </div>
    </AbsoluteFill>
  );
};
