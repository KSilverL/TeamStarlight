// Shared slide sub-components — the blocks that were copy-pasted (with drifting
// constants) across the slide files: the absolute-positioned headline h2, the CTA
// pill, plus small new blocks (Kicker, SourceCaption) for the variant rollout.

import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { blurIn, fadeDrop, riseSoft, springEnter, stagger } from "./animations";
import { displayFont, bodyFont } from "./fonts";
import { emphasisFlags, splitWords, wordOffset } from "./text";
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

/**
 * A line of type where every WORD enters and leaves on its own beat, rather than
 * the whole block moving as one — the statement slides' defining motion.
 *
 * Nothing here re-implements motion: each word composes the existing presets from
 * animations.ts (riseSoft + blurIn in, fadeDrop out) at a staggered delay. The one
 * piece of real choreography is the exit — `fadeDrop` derives its start as
 * `end - leadFrames`, so handing it a PER-WORD end is exactly what makes words
 * leave in sequence instead of together.
 *
 * Word splitting has one subtlety that matters: transforms and filters don't apply
 * to inline boxes, so each word must be `inline-block` — but the separating space
 * is emitted as a plain text node in the PARENT, never inside the span. Keeping the
 * space outside preserves it as a real line-break opportunity, so long lines still
 * wrap naturally. (Putting the space inside the span with white-space: pre is the
 * tempting version, and it welds each word+space into an unbreakable atom.) For the
 * same reason the container is a plain block, never flex.
 */
export const WordReveal: React.FC<{
  text: string;
  color: string;
  /** Colour for words named in `emphasis`. Defaults to `color`. */
  emphasisColor?: string;
  /** Literal words to highlight — matched punctuation- and case-insensitively. */
  emphasis?: string[];
  fontSize?: number;
  fontWeight?: number;
  lineHeight?: number;
  letterSpacing?: number;
  align?: "left" | "center";
  /** The slide's duration — the staggered exit is timed backwards from it. */
  durationFrames: number;
  startDelay?: number;
  stepFrames?: number;
  /** How far before the slide ends the FIRST word starts leaving. */
  exitLead?: number;
  exitStepFrames?: number;
  exitFrames?: number;
}> = ({
  text,
  color,
  emphasisColor,
  emphasis,
  fontSize: size = fontSize.display,
  fontWeight = 800,
  lineHeight = 1.04,
  letterSpacing: tracking = letterSpacing.tight,
  align = "left",
  durationFrames,
  startDelay = 0,
  stepFrames = 3,
  exitLead = 18,
  exitStepFrames = 2,
  exitFrames = 10,
}) => {
  const frame = useCurrentFrame();
  const words = splitWords(text);
  const flags = emphasisFlags(words, emphasis);

  return (
    <div
      style={{
        textAlign: align,
        color,
        fontSize: size,
        fontWeight,
        fontFamily: displayFont,
        lineHeight,
        letterSpacing: tracking,
        margin: 0,
      }}
    >
      {words.map((word, i) => {
        const delay = startDelay + stagger(i, stepFrames);
        const { dx, dy } = wordOffset(i);
        const enter = riseSoft(frame, { delay, distance: 26 + dy });
        const soft = blurIn(frame, { delay, frames: 14, maxBlur: 9 });
        // Each word gets its own end frame, so word 0 is already gone by the time
        // the last word starts to leave.
        const wordEnd = durationFrames - exitLead + stagger(i, exitStepFrames) + exitFrames;
        const leave = fadeDrop(frame, wordEnd, { leadFrames: exitFrames, distance: 14 });
        // Emphasis is colour + a hair of scale, never a weight change: bumping the
        // weight on a variable font re-measures the glyphs and reflows the line.
        const emphasised = flags[i];
        return (
          <React.Fragment key={i}>
            <span
              style={{
                display: "inline-block",
                color: emphasised ? emphasisColor ?? color : color,
                opacity: enter.opacity * leave.opacity,
                // The two translateY() from riseSoft and fadeDrop compose additively.
                transform: `translateX(${dx}px) ${enter.transform} ${leave.transform}${emphasised ? " scale(1.02)" : ""}`,
                filter: soft.filter,
              }}
            >
              {word}
            </span>
            {i < words.length - 1 ? " " : null}
          </React.Fragment>
        );
      })}
    </div>
  );
};

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
