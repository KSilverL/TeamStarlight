import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { OutroSlide as OutroSlideProps } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { fadeIn, popScale, stagger } from "../design/animations";
import { GradientWash } from "../design/backdrops";
import { CtaButton } from "../design/components";
import { bodyFont, displayFont } from "../design/fonts";
import { fontSize, letterSpacing } from "../design/tokens";

export const OutroSlide: React.FC<{ slide: OutroSlideProps; accentColor: string; secondaryColor: string; primaryColor: string; theme?: Theme }> = ({
  slide,
  accentColor,
  secondaryColor,
  primaryColor,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "badge";

  const tagline = slide.tagline ? (
    <p style={{ color: textColor, opacity: 0.7, fontSize: fontSize.body, fontFamily: bodyFont, marginTop: 12 }}>{slide.tagline}</p>
  ) : null;
  const contact = slide.contact ? (
    <p style={{ color: textColor, opacity: 0.7, fontSize: fontSize.caption, fontFamily: bodyFont, marginTop: 24 }}>{slide.contact}</p>
  ) : null;

  // ── sweep: per-letter brand-name cascade over a diagonal gradient sweep ────
  if (variant === "sweep") {
    const letters = Array.from(slide.brandName);
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} strength={0.32} />
        <div style={{ textAlign: "center" }}>
          <div style={{ display: "flex", justifyContent: "center" }}>
            {letters.map((ch, i) => {
              const enter = popScale(frame, fps, { delay: stagger(i, 3), damping: 13 });
              return (
                <span
                  key={i}
                  style={{
                    ...enter,
                    display: "inline-block",
                    color: textColor,
                    fontSize: fontSize.title,
                    fontWeight: 900,
                    fontFamily: displayFont,
                    letterSpacing: letterSpacing.wide,
                    whiteSpace: "pre",
                  }}
                >
                  {ch}
                </span>
              );
            })}
          </div>
          {tagline}
          <div style={{ marginTop: 36 }}>
            <CtaButton backgroundColor={accentColor} color={textColor} delay={stagger(letters.length, 3) + 4}>
              {slide.ctaLabel}
            </CtaButton>
          </div>
          {contact}
        </div>
      </AbsoluteFill>
    );
  }

  // ── badge (default): centred brand name + CTA pill ────────────────────────
  const fade = fadeIn(frame, { frames: 15 });
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      <div style={{ opacity: fade, textAlign: "center" }}>
        <h1 style={{ color: textColor, fontSize: fontSize.title, fontWeight: 900, fontFamily: displayFont, letterSpacing: letterSpacing.wide, margin: 0 }}>
          {slide.brandName}
        </h1>
        {tagline}
        <div style={{ marginTop: 36 }}>
          <CtaButton backgroundColor={accentColor} color={textColor}>
            {slide.ctaLabel}
          </CtaButton>
        </div>
        {contact}
      </div>
    </AbsoluteFill>
  );
};
