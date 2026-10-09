import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { ColdOpenSlide as ColdOpenSlideProps } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { filmGrade, kenBurns, maskWipe, progress, riseSoft, stagger } from "../design/animations";
import { PixelMosaic } from "../design/backdrops";
import { Kicker, WordReveal } from "../design/components";
import { bodyFont } from "../design/fonts";
import { withAlpha } from "../design/palettes";
import { SHAPE_CLIP } from "../design/shapes";
import { splitWords } from "../design/text";
import { accentGlow, fontSize, letterSpacing, radius, space } from "../design/tokens";

/**
 * The video's opening title: an establishing stock-footage shot behind a title
 * lockup, framed by a letterbox matte CUT OUT OF the live pixel-mosaic field.
 *
 * The matte is the whole idea. One full-frame <PixelMosaic> sits at the bottom of the
 * stack and the footage layer above it is clipped with an animating `inset()`. At
 * frame 0 the inset is BAR_SHUT top and bottom, so the frame is effectively all
 * mosaic with a slit of light through the middle; it relaxes to a resting matte over
 * the opening beat. That single move buys the "something is starting" cue that
 * MediaStatementSlide never gives (it is a mid-video beat, so it opens at full
 * brightness), an anamorphic frame, the animated mosaic visible in every variant, and
 * a no-footage degradation that is continuous with the good case rather than a
 * different-looking slide. It costs exactly what inset_card costs: one mosaic, one
 * <OffthreadVideo>.
 *
 * The other structural difference from every other text slide: THE TITLE NEVER
 * EXITS. WordReveal bakes in a staggered fadeDrop, and `exitLead={0}` suppresses it
 * through the existing API — wordEnd lands past the last frame, so interpolate's
 * clamp holds opacity at 1. `statement` and `media_statement` both dismantle their
 * own text before the cut, which is right for a beat inside an argument and wrong for
 * a title. It is also why this type belongs at slide 1 and nowhere else.
 *
 * Note every beat below is either front-loaded on an absolute frame (so it simply
 * holds longer) or expressed through kenBurns(frame, duration)/progress. Nothing is
 * keyed to `duration - N` the way mosaic_reveal's refill window is, because jobs.py
 * stretches durationFrames AFTER clamp_duration to fit a narration line — a stretched
 * cold_open just breathes more.
 */

// Matte depth at rest, as a % of frame height. Portrait needs a deeper bar to read as
// a matte at all; landscape at 7.5% lands near 2.1:1, about cinemascope.
const barRestFor = (width: number, height: number) => (height > width ? 9 : 7.5);
// Not 50: a sliver of image at frame 0 reads as light through an opening gap, and it
// avoids a degenerate zero-height clip rect.
const BAR_SHUT = 49.5;
// Ease-out quad. Local because it is a handful of call sites in one file; promote it
// to design/animations.ts if a second slide ever wants it.
const easeOut = (t: number) => t * (2 - t);
// mediaDurationFrames comes from a provider-reported float duration, so it can be a
// frame optimistic; running the decoder off the end of a clip is the one request
// guaranteed to fail. Two frames is imperceptible. (Same constant, same reason, as
// MediaStatementSlide.)
const CLIP_TAIL_MARGIN = 2;

export const ColdOpenSlide: React.FC<{
  slide: ColdOpenSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "title_card";
  const hasClip = Boolean(slide.mediaLocalPath);
  const duration = slide.durationFrames;
  const barRest = barRestFor(width, height);
  const words = splitWords(slide.headline).length;

  /**
   * The clip, graded and zooming.
   *
   * Structurally MediaStatementSlide's `clip()`, including the reason a short clip is
   * SLOWED rather than looped: <OffthreadVideo> has no `loop` prop in Remotion 4, and
   * the documented <Loop> wrapper makes the compositor fail with "No frame found at
   * position N" on positions it serves fine unwrapped. Stretching sidesteps it and has
   * no wrap seam, which suits ambient establishing footage anyway. Worst case here is
   * bounded by PexelsVideoSearch's 4s floor against the 240-frame ceiling, so ~0.49x —
   * slow motion, which is on-brief for an opener.
   *
   * Three nested divs, not two: the grade `filter` and the Ken Burns `transform` must
   * not share an element (see filmGrade's note in design/animations.ts).
   *
   * `muted`: stock clips carry their own audio, which would fight the narration.
   */
  const clip = (kb: { from: number; to: number; panX?: number; panY?: number }, grade: string) => {
    const clipFrames = slide.mediaDurationFrames
      ? Math.max(1, slide.mediaDurationFrames - CLIP_TAIL_MARGIN)
      : null;
    const playbackRate =
      clipFrames && clipFrames < duration ? Math.max(0.1, clipFrames / duration) : 1;
    return (
      <div style={{ width: "100%", height: "100%", overflow: "hidden", filter: grade }}>
        <div style={{ width: "100%", height: "100%", transform: kenBurns(frame, duration, kb) }}>
          <OffthreadVideo
            src={staticFile(slide.mediaLocalPath as string)}
            muted
            playbackRate={playbackRate}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        </div>
      </div>
    );
  };

  /**
   * Kicker, accent rule, title, subtext — the title lockup, shared by every variant
   * with per-variant timing and alignment. Local rather than exported: it is used once
   * per branch of this file, the way MediaStatementSlide keeps `statement()` local.
   */
  const lockup = (opts: {
    align: "left" | "center";
    kickerDelay: number;
    ruleDelay: number;
    ruleWidth: string;
    titleDelay: number;
    titleStep: number;
    titleSize: number;
    titleZoom: number;
    titleOrigin: string;
    /** A filled accent slab behind the kicker (`trailer`) instead of a bare eyebrow. */
    slate?: boolean;
    style: React.CSSProperties;
  }) => {
    // The subtext waits for the last word of the title to land, so the two never
    // animate over each other. Capped so a long title can't push it off the slide.
    const subDelay = Math.min(opts.titleDelay + stagger(words, opts.titleStep) + 6, 78);
    const subEnter = riseSoft(frame, { delay: subDelay, distance: 18, fadeFrames: 16, riseFrames: 20 });
    return (
      <div style={{ position: "absolute", textAlign: opts.align, ...opts.style }}>
        {slide.kicker &&
          (opts.slate ? (
            <div
              style={{
                display: "inline-block",
                padding: `${space(1) - 2}px ${space(2) - 2}px`,
                borderRadius: radius.bar,
                backgroundColor: accentColor,
                marginBottom: space(2),
                ...maskWipe(frame, { delay: opts.kickerDelay, frames: 9, from: "left" }),
              }}
            >
              {/* Kicker text in primaryColor, not textColor: it sits ON the accent fill,
                  and that is the one pairing guaranteed to contrast for any brand accent. */}
              <Kicker color={primaryColor}>{slide.kicker}</Kicker>
            </div>
          ) : (
            <div
              style={{
                marginBottom: space(2),
                ...riseSoft(frame, { delay: opts.kickerDelay, distance: 14, fadeFrames: 14 }),
              }}
            >
              <Kicker color={accentColor}>{slide.kicker}</Kicker>
            </div>
          ))}
        <div
          style={{
            height: 3,
            width: `${parseFloat(opts.ruleWidth) * easeOut(progress(frame, { from: opts.ruleDelay, to: opts.ruleDelay + 18 }))}%`,
            margin: opts.align === "center" ? `0 auto ${space(3)}px` : `0 0 ${space(3)}px`,
            backgroundColor: accentColor,
            borderRadius: radius.pill,
            boxShadow: accentGlow(accentColor, 16),
          }}
        />
        <div
          style={{
            transform: kenBurns(frame, duration, { from: 1, to: opts.titleZoom }),
            transformOrigin: opts.titleOrigin,
          }}
        >
          <WordReveal
            text={slide.headline}
            color={textColor}
            emphasisColor={accentColor}
            emphasis={slide.emphasisWords}
            fontSize={opts.titleSize}
            lineHeight={1.0}
            letterSpacing={letterSpacing.tight}
            align={opts.align}
            durationFrames={duration}
            startDelay={opts.titleDelay}
            stepFrames={opts.titleStep}
            exitLead={0}
          />
        </div>
        {slide.subtext && (
          <p
            style={{
              color: textColor,
              fontSize: fontSize.body,
              fontFamily: bodyFont,
              margin: `${space(3)}px 0 0`,
              ...subEnter,
              // Multiplied INTO the entrance, not spread after it: a bare `opacity: 0.82`
              // either overwrites the fade or gets overwritten by it, depending on order.
              opacity: subEnter.opacity * 0.82,
            }}
          >
            {slide.subtext}
          </p>
        )}
      </div>
    );
  };

  // ── No clip resolved (search miss, download failure, or the Lambda backend) ──
  // One branch for all three variants — `slide.variant` is deliberately unused here,
  // matching how media_statement's fallback also ignores it. It still reads as an
  // OPENER because it keeps the two moves that carry the genre: the matte opens (as
  // opaque bars — with no footage layer to clip, the mask inverts), and the mosaic
  // field ASSEMBLES out of bare primaryColor rather than simply being there. A brand
  // field arriving and settling behind matte bars is a studio ident, which is a real
  // opener form, not a consolation prize.
  if (!hasClip) {
    const barPct = BAR_SHUT + (barRest - BAR_SHUT) * easeOut(progress(frame, { to: 24 }));
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        <AbsoluteFill
          style={{
            overflow: "hidden",
            transform: kenBurns(frame, duration, { from: 1.06, to: 1.0 }),
            transformOrigin: "50% 50%",
          }}
        >
          <PixelMosaic
            primaryColor={primaryColor}
            secondaryColor={secondaryColor}
            accentColor={accentColor}
            contrast={0.9}
            dissolve={1 - easeOut(progress(frame, { to: 22 }))}
          />
        </AbsoluteFill>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: `${barPct}%`, backgroundColor: primaryColor }} />
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: `${barPct}%`, backgroundColor: primaryColor }} />
        {/* Six frames earlier than title_card throughout: there is no shot to establish. */}
        {lockup({
          align: "center",
          kickerDelay: 18,
          ruleDelay: 24,
          ruleWidth: "14",
          titleDelay: 28,
          titleStep: 5,
          titleSize: fontSize.display,
          titleZoom: 1.045,
          titleOrigin: "50% 50%",
          style: { left: "10%", right: "10%", top: "50%", transform: "translateY(-50%)" },
        })}
      </AbsoluteFill>
    );
  }

  // ── horizon: footage across the top under an angled seam, title below on the
  // live mosaic field. Inverts BOTH inset_card (text on top / rounded media card
  // bleeding off the bottom) and statement's `band` (mosaic on top / straight seam).
  if (variant === "horizon") {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        {/* The dissolve run BACKWARDS: cells materialise out of bare primaryColor in
            hash order instead of scattering away. Same code path as mosaic_reveal,
            opposite direction — which is exactly why it doesn't read as the same
            effect. mosaic_reveal takes the field away; this builds it. */}
        <PixelMosaic
          primaryColor={primaryColor}
          secondaryColor={secondaryColor}
          accentColor={accentColor}
          contrast={0.85}
          dissolve={1 - easeOut(progress(frame, { to: 18 }))}
        />
        {/* Two nested divs are mandatory: maskWipe returns a clipPath, and one element
            cannot carry both it and the seam's shape clip. */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: "58%",
            clipPath: SHAPE_CLIP.horizonCut,
            overflow: "hidden",
          }}
        >
          <div style={{ width: "100%", height: "100%", ...maskWipe(frame, { delay: 4, frames: 26, from: "top" }) }}>
            {clip(
              { from: 1.12, to: 1.0, panX: 1.6 },
              filmGrade(frame, { frames: 28, saturate: 0.4, contrast: 1.1, brightness: 0.72 }),
            )}
            {/* Vignette inside the panel, so the diagonal seam sits INTO the mosaic
                instead of looking pasted over it. */}
            <AbsoluteFill
              style={{
                background: `linear-gradient(0deg, ${withAlpha(primaryColor, 0.6)} 0%, transparent 24%)`,
              }}
            />
          </div>
        </div>
        {/* fontSize.h1, not display: this block owns ~30% of frame height and sits
            directly on a busy field. */}
        {lockup({
          align: "left",
          kickerDelay: 24,
          ruleDelay: 28,
          ruleWidth: "9",
          titleDelay: 32,
          titleStep: 4,
          titleSize: fontSize.h1,
          titleZoom: 1.035,
          titleOrigin: "0% 50%",
          style: { left: "9%", right: "14%", top: "64%" },
        })}
      </AbsoluteFill>
    );
  }

  const barPct =
    variant === "trailer"
      ? // Slams shut over 10 frames, UNDER the flash — so the frame is already matted
        // when the flash clears. The cut you feel rather than see.
        BAR_SHUT + (barRest - BAR_SHUT) * easeOut(progress(frame, { to: 10 }))
      : // Irises open over 24, decelerating into place rather than stopping dead.
        BAR_SHUT + (barRest - BAR_SHUT) * easeOut(progress(frame, { to: 24 }));

  // ── trailer: the same family as title_card, inverted on every axis — flash-frame
  // open, hot grade settling to neutral, a push-IN instead of a settle, a hard
  // left-aligned lockup low in the frame, and roughly double the word cadence.
  if (variant === "trailer") {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        <PixelMosaic
          primaryColor={primaryColor}
          secondaryColor={secondaryColor}
          accentColor={accentColor}
          contrast={0.9}
        />
        <AbsoluteFill style={{ clipPath: `inset(${barPct}% 0)` }}>
          {clip(
            { from: 1.0, to: 1.15, panX: -2.5 },
            filmGrade(frame, { frames: 14, saturate: 1.45, contrast: 1.18, brightness: 1.12 }),
          )}
          <AbsoluteFill
            style={{
              background:
                `linear-gradient(90deg, ${withAlpha(primaryColor, 0.85)} 0%, ${withAlpha(primaryColor, 0.32)} 38%, transparent 64%), ` +
                `linear-gradient(0deg, ${withAlpha(primaryColor, 0.5)} 0%, transparent 26%)`,
            }}
          />
        </AbsoluteFill>
        {/* textColor, so it is a white flash on a dark storyboard and a near-black one
            on a light storyboard — theme-correct for free. */}
        <AbsoluteFill style={{ backgroundColor: textColor, opacity: 1 - progress(frame, { to: 5 }) }} />
        {/* The asymmetric right inset forces early line breaks into a designed rag —
            the trick StatementSlide documents. */}
        {lockup({
          align: "left",
          slate: true,
          kickerDelay: 4,
          ruleDelay: 12 + stagger(words, 2),
          ruleWidth: "100",
          titleDelay: 10,
          titleStep: 2,
          titleSize: fontSize.display,
          titleZoom: 1.05,
          titleOrigin: "0% 100%",
          style: { left: "8%", right: "22%", bottom: "18%" },
        })}
      </AbsoluteFill>
    );
  }

  // ── title_card (default): the matte irises open on a cold, dim shot that blooms
  // into colour exactly as the title lands, centred in the lower third. The top ~60%
  // of frame stays pure image for the whole slide — that empty upper field is what
  // reads as an establishing shot rather than a caption over B-roll.
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      <PixelMosaic
        primaryColor={primaryColor}
        secondaryColor={secondaryColor}
        accentColor={accentColor}
        contrast={0.9}
      />
      <AbsoluteFill style={{ clipPath: `inset(${barPct}% 0)` }}>
        {clip(
          { from: 1.18, to: 1.02, panY: -1.2 },
          filmGrade(frame, { frames: 34, saturate: 0.25, contrast: 1.25, brightness: 0.6 }),
        )}
        {/* Accent cast over the opening beat, INSIDE the clipped layer so it tints the
            image and not the mosaic bars. */}
        <AbsoluteFill
          style={{
            background: withAlpha(accentColor, 0.28 * (1 - progress(frame, { to: 40 }))),
            mixBlendMode: "overlay",
          }}
        />
        {/* Bottom-weighted, the inverse of full_bleed's top scrim — which is what flips
            the whole composition rather than just moving the text. */}
        <AbsoluteFill
          style={{
            background: `linear-gradient(0deg, ${withAlpha(primaryColor, 0.88)} 0%, ${withAlpha(primaryColor, 0.42)} 30%, transparent 56%)`,
          }}
        />
      </AbsoluteFill>
      {/* transformOrigin bottom: the title creeps TOWARD camera while the shot settles
          AWAY from it, and the lockup's bottom margin stays put. */}
      {lockup({
        align: "center",
        kickerDelay: 22,
        ruleDelay: 28,
        ruleWidth: "14",
        titleDelay: 34,
        titleStep: 5,
        titleSize: fontSize.display,
        titleZoom: 1.045,
        titleOrigin: "50% 100%",
        style: { left: "10%", right: "10%", bottom: "16%" },
      })}
    </AbsoluteFill>
  );
};
