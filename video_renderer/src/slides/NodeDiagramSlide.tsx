import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { NodeDiagramSlide as NodeDiagramSlideProps } from "../types";
import { connectorForTheme, textColorForTheme, type Theme } from "./theme";
import { fadeIn, popScale, springEnter, stagger } from "../design/animations";
import { SlideHeadline } from "../design/components";
import { paletteFor } from "../design/palettes";
import { displayFont } from "../design/fonts";
import { fontSize, radius } from "../design/tokens";

export const NodeDiagramSlide: React.FC<{
  slide: NodeDiagramSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const variant = slide.variant ?? "chain";
  const textColor = textColorForTheme(theme);
  const palette = paletteFor("brand", { accentColor, secondaryColor }, theme);
  const nodeColor = (i: number) => palette[i % 2];

  const headline = slide.headline ? <SlideHeadline color={textColor}>{slide.headline}</SlideHeadline> : null;

  // ── hub: first node centred, the rest radiate out with drawn-on connectors ─
  if (variant === "hub") {
    const [hub, ...spokes] = slide.nodes;
    const cx = width / 2;
    const cy = height / 2;
    const R = Math.min(width, height) * 0.32;
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor }}>
        {headline}
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          {spokes.map((_, i) => {
            const angle = (i / spokes.length) * Math.PI * 2 - Math.PI / 2;
            const x = cx + Math.cos(angle) * R;
            const y = cy + Math.sin(angle) * R;
            const draw = springEnter(frame, fps, { delay: stagger(i + 1, 8), damping: 18 });
            return (
              <line
                key={i}
                x1={cx} y1={cy}
                x2={cx + (x - cx) * draw} y2={cy + (y - cy) * draw}
                stroke={connectorForTheme(theme)} strokeWidth={3}
              />
            );
          })}
        </svg>
        {spokes.map((node, i) => {
          const angle = (i / spokes.length) * Math.PI * 2 - Math.PI / 2;
          const x = cx + Math.cos(angle) * R;
          const y = cy + Math.sin(angle) * R;
          const delay = stagger(i + 1, 8);
          const scale = springEnter(frame, fps, { delay, damping: 14 });
          return (
            <div key={i} style={{ position: "absolute", left: x, top: y, transform: `translate(-50%, -50%) scale(${scale})`, opacity: fadeIn(frame, { delay, frames: 10 }) }}>
              <div style={{ padding: "12px 20px", borderRadius: radius.node, backgroundColor: nodeColor(i + 1), color: textColor, fontSize: fontSize.label - 2, fontWeight: 800, fontFamily: displayFont, textAlign: "center", whiteSpace: "nowrap" }}>
                {node}
              </div>
            </div>
          );
        })}
        <div style={{ position: "absolute", left: cx, top: cy, transform: `translate(-50%, -50%) scale(${springEnter(frame, fps, { damping: 12 })})` }}>
          <div style={{ padding: "22px 32px", borderRadius: radius.node, backgroundColor: accentColor, color: textColor, fontSize: fontSize.label, fontWeight: 800, fontFamily: displayFont, textAlign: "center" }}>
            {hub}
          </div>
        </div>
      </AbsoluteFill>
    );
  }

  // ── steps: ascending numbered staircase ───────────────────────────────────
  if (variant === "steps") {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "flex-end", alignItems: "center", paddingBottom: "12%" }}>
        {headline}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 16, width: "84%", justifyContent: "center" }}>
          {slide.nodes.map((node, i) => {
            const enter = popScale(frame, fps, { delay: stagger(i, 9), damping: 15 });
            const stepH = 120 + i * 90;
            return (
              <div key={i} style={{ ...enter, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end" }}>
                <div style={{ color: textColor, fontSize: fontSize.caption, fontFamily: displayFont, fontWeight: 800, marginBottom: 10, opacity: 0.6 }}>{i + 1}</div>
                <div
                  style={{
                    width: 150,
                    height: stepH,
                    borderRadius: radius.node,
                    backgroundColor: nodeColor(i),
                    color: textColor,
                    fontSize: fontSize.caption,
                    fontWeight: 800,
                    fontFamily: displayFont,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    textAlign: "center",
                    padding: 12,
                  }}
                >
                  {node}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }

  // ── chain (default): connected sequence, vertical on 9:16, horizontal on 16:9 ─
  const vertical = height > width;
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {headline}
      <div style={{ display: "flex", flexDirection: vertical ? "column" : "row", alignItems: "center", gap: vertical ? 28 : 36 }}>
        {slide.nodes.map((node, i) => {
          const delay = stagger(i, 10);
          const enter = popScale(frame, fps, { delay, damping: 14 });
          const lineOpacity = fadeIn(frame, { delay: delay + 6, frames: 10 });
          return (
            <React.Fragment key={i}>
              {i > 0 && (
                <div style={{ backgroundColor: connectorForTheme(theme), opacity: lineOpacity, width: vertical ? 3 : 48, height: vertical ? 48 : 3 }} />
              )}
              <div
                style={{
                  ...enter,
                  padding: "18px 28px",
                  borderRadius: radius.node,
                  backgroundColor: nodeColor(i),
                  color: textColor,
                  fontSize: fontSize.label,
                  fontWeight: 800,
                  fontFamily: displayFont,
                  textAlign: "center",
                  minWidth: 120,
                }}
              >
                {node}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
