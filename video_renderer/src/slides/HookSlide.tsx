import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { HookSlide as HookSlideProps } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { blurIn, maskWipe, riseSoft, springEnter } from "../design/animations";
import { BackdropOrbs, GradientWash, GridPattern } from "../design/backdrops";
import { Kicker } from "../design/components";
import { bodyFont, displayFont } from "../design/fonts";
import { SHAPE_CLIP, SHAPE_RADIUS } from "../design/shapes";
import { fontSize } from "../design/tokens";

// Local, per-slide background treatment (HookSlideSpec.background) — layered above
// the primaryColor fill, below the content. Distinct from the storyboard-wide
// atmosphere in Composition.tsx (this one is stronger and slide-scoped).
const LocalBackground: React.FC<{
  background: HookSlideProps["background"];
  accentColor: string;
  secondaryColor: string;
  theme?: Theme;
}> = ({ background, accentColor, secondaryColor, theme }) => {
  switch (background) {
    case "gradient":
      return <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} strength={0.28} />;
    case "orbs":
      return <BackdropOrbs accentColor={accentColor} secondaryColor={secondaryColor} opacity={0.35} />;
    case "grid":
      return <GridPattern color={textColorForTheme(theme)} opacity={0.1} />;
    case "solid":
    default:
      return null;
  }
};

export const HookSlide: React.FC<{ slide: HookSlideProps; accentColor: string; secondaryColor: string; primaryColor: string; theme?: Theme }> = ({
  slide,
  accentColor,
  secondaryColor,
  primaryColor,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "spotlight";
  const hasImage = Boolean(slide.imageLocalPath);

  const kicker = slide.kicker ? <Kicker color={accentColor}>{slide.kicker}</Kicker> : null;

  // ── poster: no image, giant headline over a gradient wash ─────────────────
  if (variant === "poster") {
    const enter = blurIn(frame, { frames: 18 });
    const underline = springEnter(frame, fps, { delay: 12, damping: 18 });
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", padding: "0 8%" }}>
        <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} strength={0.35} />
        <LocalBackground background={slide.background} accentColor={accentColor} secondaryColor={secondaryColor} theme={theme} />
        <div style={{ ...enter }}>
          {kicker}
          <h1 style={{ color: textColor, fontSize: fontSize.display, fontWeight: 800, fontFamily: displayFont, margin: "12px 0 0", lineHeight: 1.02 }}>
            {slide.headline}
          </h1>
          <div style={{ height: 10, marginTop: 24, width: `${60 * underline}%`, backgroundColor: accentColor, borderRadius: 999 }} />
          {slide.subtext && (
            <p style={{ color: textColor, opacity: 0.8, fontSize: fontSize.body, fontFamily: bodyFont, marginTop: 24 }}>{slide.subtext}</p>
          )}
        </div>
      </AbsoluteFill>
    );
  }

  // ── split: image fills one diagonal half, headline the other ──────────────
  if (variant === "split" && hasImage) {
    const imgWipe = maskWipe(frame, { frames: 20, from: "top" });
    const headlineEnter = riseSoft(frame, { delay: 8 });
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        <LocalBackground background={slide.background} accentColor={accentColor} secondaryColor={secondaryColor} theme={theme} />
        <AbsoluteFill style={{ ...imgWipe, clipPath: SHAPE_CLIP.diagonalCut }}>
          <Img src={staticFile(slide.imageLocalPath as string)} style={{ width: "100%", height: "62%", objectFit: "cover" }} />
        </AbsoluteFill>
        <div style={{ position: "absolute", bottom: "8%", width: "84%", left: "8%", ...headlineEnter }}>
          {kicker}
          <h1 style={{ color: textColor, fontSize: fontSize.h1, fontWeight: 800, fontFamily: displayFont, margin: "8px 0 0", lineHeight: 1.08 }}>
            {slide.headline}
          </h1>
          {slide.subtext && (
            <p style={{ color: textColor, opacity: 0.8, fontSize: fontSize.body, fontFamily: bodyFont, marginTop: 14 }}>{slide.subtext}</p>
          )}
        </div>
      </AbsoluteFill>
    );
  }

  // ── spotlight (default): centred image on a shape, headline below ─────────
  const scale = springEnter(frame, fps, { damping: 14, mass: 0.6 });
  const headlineEnter = riseSoft(frame);
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      <LocalBackground background={slide.background} accentColor={accentColor} secondaryColor={secondaryColor} theme={theme} />
      {hasImage && (
        <div
          style={{
            position: "absolute",
            width: "55%",
            aspectRatio: "1 / 1",
            borderRadius: SHAPE_RADIUS[slide.shape],
            backgroundColor: accentColor,
            transform: `scale(${scale})`,
            overflow: "hidden",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          {/* imageLocalPath is job-directory-relative (e.g. "images/0.png"), served via
              the render's --public-dir; staticFile() resolves it to a loadable URL —
              Chromium's headless renderer refuses file:// resources outright. */}
          <Img src={staticFile(slide.imageLocalPath as string)} style={{ width: "85%", objectFit: "contain" }} />
        </div>
      )}
      <div style={{ position: "absolute", bottom: "12%", width: "85%", textAlign: "center", ...headlineEnter }}>
        {slide.kicker && <div style={{ marginBottom: 8 }}>{kicker}</div>}
        <h1 style={{ color: textColor, fontSize: fontSize.h1, fontWeight: 800, fontFamily: displayFont, margin: 0, lineHeight: 1.1 }}>
          {slide.headline}
        </h1>
        {slide.subtext && (
          <p style={{ color: textColor, opacity: 0.8, fontSize: fontSize.body, fontFamily: bodyFont, marginTop: 16 }}>{slide.subtext}</p>
        )}
      </div>
    </AbsoluteFill>
  );
};
