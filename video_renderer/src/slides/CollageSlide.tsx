import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { CollageSlide as CollageSlideProps, ResolvedImage } from "../types";
import { textColorForTheme, type Theme } from "./theme";
import { fadeIn, popScale, stagger } from "../design/animations";
import { SlideHeadline } from "../design/components";
import { paletteFor } from "../design/palettes";
import { bodyFont } from "../design/fonts";
import { fontSize } from "../design/tokens";

// Geometric-circle layouts (the original three). Slot positions as % of the frame.
const CIRCLE_SLOTS: Record<"grid" | "scatter" | "stack", Array<{ top: string; left: string; size: string }>> = {
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

export const CollageSlide: React.FC<{ slide: CollageSlideProps; accentColor: string; secondaryColor: string; primaryColor: string; theme?: Theme }> = ({
  slide,
  accentColor,
  secondaryColor,
  primaryColor,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const layout = slide.layout ?? "grid";
  const textColor = textColorForTheme(theme);
  const palette = paletteFor("brand", { accentColor, secondaryColor }, theme);
  const caption = (i: number) => slide.captions?.[i];

  const headline = slide.headline ? (
    <SlideHeadline color={textColor} top="4%">
      {slide.headline}
    </SlideHeadline>
  ) : null;

  // ── filmstrip: a horizontal strip that slowly pans across ─────────────────
  if (layout === "filmstrip") {
    const images = slide.resolvedImages;
    const pan = interpolate(frame, [0, slide.durationFrames], [0, -width * 0.25], { extrapolateRight: "clamp" });
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center" }}>
        {headline}
        <div style={{ display: "flex", gap: 24, alignItems: "center", transform: `translateX(${pan}px)`, paddingLeft: "8%" }}>
          {images.map((image, i) => {
            const enter = fadeIn(frame, { delay: stagger(i, 6), frames: 12 });
            return (
              <div key={i} style={{ opacity: enter, flex: "0 0 auto" }}>
                <div style={{ width: width * 0.5, height: width * 0.5, borderRadius: 20, overflow: "hidden", backgroundColor: palette[i % palette.length], display: "flex", justifyContent: "center", alignItems: "center" }}>
                  {image?.localPath && <Img src={staticFile(image.localPath)} style={{ width: "88%", objectFit: "contain" }} />}
                </div>
                {caption(i) && <div style={{ color: textColor, fontSize: fontSize.caption, fontFamily: bodyFont, marginTop: 12, textAlign: "center" }}>{caption(i)}</div>}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }

  // ── polaroid: white-bordered cards drop in, gently rotated ────────────────
  if (layout === "polaroid") {
    const images = slide.resolvedImages.slice(0, 4);
    const rotations = [-6, 5, -3, 7];
    const positions = [
      { top: "18%", left: "10%" }, { top: "22%", left: "52%" },
      { top: "52%", left: "16%" }, { top: "50%", left: "54%" },
    ];
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        {headline}
        {images.map((image, i) => {
          const enter = popScale(frame, fps, { delay: stagger(i, 8), damping: 13 });
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                ...positions[i],
                width: "36%",
                background: "#fff",
                padding: "12px 12px 16px",
                borderRadius: 6,
                boxShadow: "0 8px 30px rgba(0,0,0,0.45)",
                opacity: enter.opacity,
                transform: `${enter.transform} rotate(${rotations[i]}deg)`,
              }}
            >
              <div style={{ width: "100%", aspectRatio: "1 / 1", backgroundColor: palette[i % palette.length], borderRadius: 2, overflow: "hidden", display: "flex", justifyContent: "center", alignItems: "center" }}>
                {image?.localPath && <Img src={staticFile(image.localPath)} style={{ width: "92%", objectFit: "contain" }} />}
              </div>
              {caption(i) && <div style={{ color: "#111", fontSize: fontSize.tick, fontFamily: bodyFont, marginTop: 8, textAlign: "center" }}>{caption(i)}</div>}
            </div>
          );
        })}
      </AbsoluteFill>
    );
  }

  // ── grid / scatter / stack (default circle layouts) ───────────────────────
  const slots = CIRCLE_SLOTS[layout as "grid" | "scatter" | "stack"] ?? CIRCLE_SLOTS.grid;
  const images = slide.resolvedImages.slice(0, slots.length);
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {headline}
      {slots.map((slot, i) => {
        const image: ResolvedImage | undefined = images[i];
        const enter = popScale(frame, fps, { delay: stagger(i, 6), damping: 15 });
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
              backgroundColor: palette[i % 2],
              ...enter,
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
