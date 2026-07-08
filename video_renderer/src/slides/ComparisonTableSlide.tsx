import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { ComparisonTableSlide as ComparisonTableSlideProps } from "../types";
import { surfaceWashForTheme, textColorForTheme, type Theme } from "./theme";
import { fadeIn, slideIn, stagger } from "../design/animations";
import { SlideHeadline } from "../design/components";
import { bodyFont, displayFont } from "../design/fonts";
import { accentGlow, fontSize, radius } from "../design/tokens";

export const ComparisonTableSlide: React.FC<{
  slide: ComparisonTableSlideProps;
  accentColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const variant = slide.variant ?? "rows";
  const textColor = textColorForTheme(theme);

  const headline = slide.headline ? <SlideHeadline color={textColor}>{slide.headline}</SlideHeadline> : null;

  // ── versus: two-column head-to-head with a centre VS badge ────────────────
  if (variant === "versus" && slide.columns.length === 2) {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        {headline}
        <div style={{ width: "86%", display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "0 4%" }}>
            {slide.columns.map((col, i) => (
              <div key={i} style={{ color: i === 0 ? accentColor : textColor, fontSize: fontSize.label, fontWeight: 800, fontFamily: displayFont }}>{col}</div>
            ))}
          </div>
          {slide.rows.map((row, rIdx) => {
            const delay = stagger(rIdx, 12);
            const leftEnter = slideIn(frame, fps, { delay, damping: 16, distance: 50 });
            const rightEnter = slideIn(frame, fps, { delay, damping: 16, distance: -50 });
            return (
              <div key={rIdx} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ ...leftEnter, flex: 1, textAlign: "center", color: textColor, fontSize: fontSize.label, fontWeight: 700, fontFamily: displayFont, padding: "16px", borderRadius: radius.cell, backgroundColor: surfaceWashForTheme(theme) }}>
                  {row.values[0]}
                </div>
                <div style={{ color: accentColor, fontSize: fontSize.caption, fontWeight: 900, fontFamily: displayFont, opacity: fadeIn(frame, { delay, frames: 10 }) }}>VS</div>
                <div style={{ ...rightEnter, flex: 1, textAlign: "center", color: textColor, fontSize: fontSize.label, fontWeight: 700, fontFamily: displayFont, padding: "16px", borderRadius: radius.cell, backgroundColor: surfaceWashForTheme(theme) }}>
                  {row.values[1]}
                </div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }

  // ── scorecard: pill cells, winning column highlighted per row ─────────────
  if (variant === "scorecard") {
    const columnTemplate = `1.4fr repeat(${slide.columns.length}, 1fr)`;
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        {headline}
        <div style={{ width: "86%", display: "grid", gridTemplateColumns: columnTemplate, rowGap: 16, columnGap: 12 }}>
          <div />
          {slide.columns.map((col, i) => (
            <div key={i} style={{ color: textColor, opacity: 0.7, fontSize: fontSize.caption, fontWeight: 700, fontFamily: bodyFont, textAlign: "center" }}>{col}</div>
          ))}
          {slide.rows.map((row, rIdx) => {
            const rowStyle = slideIn(frame, fps, { delay: stagger(rIdx, 12), damping: 16, distance: 40 });
            return (
              <React.Fragment key={rIdx}>
                <div style={{ ...rowStyle, color: textColor, fontWeight: 800, fontSize: fontSize.label - 2, fontFamily: displayFont, display: "flex", alignItems: "center" }}>{row.label}</div>
                {row.values.map((value, cIdx) => {
                  const isWinner = slide.highlightColumn === cIdx;
                  return (
                    <div
                      key={cIdx}
                      style={{
                        ...rowStyle,
                        color: isWinner ? primaryColor : textColor,
                        fontSize: fontSize.caption,
                        fontFamily: bodyFont,
                        fontWeight: isWinner ? 800 : 500,
                        textAlign: "center",
                        padding: "12px 8px",
                        borderRadius: radius.pill,
                        backgroundColor: isWinner ? accentColor : surfaceWashForTheme(theme),
                        boxShadow: isWinner ? accentGlow(accentColor, 16) : undefined,
                      }}
                    >
                      {isWinner ? `✓ ${value}` : value}
                    </div>
                  );
                })}
              </React.Fragment>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }

  // ── rows (default): grid revealed row by row ──────────────────────────────
  const columnTemplate = `1.4fr repeat(${slide.columns.length}, 1fr)`;
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      {headline}
      <div style={{ width: "84%", display: "grid", gridTemplateColumns: columnTemplate, rowGap: 14, columnGap: 10 }}>
        <div />
        {slide.columns.map((col, i) => (
          <div key={i} style={{ color: textColor, opacity: 0.7, fontSize: fontSize.caption, fontWeight: 700, fontFamily: bodyFont, textAlign: "center" }}>{col}</div>
        ))}
        {slide.rows.map((row, rIdx) => {
          const rowStyle = slideIn(frame, fps, { delay: stagger(rIdx, 12), damping: 16, distance: 40 });
          return (
            <React.Fragment key={rIdx}>
              <div style={{ ...rowStyle, color: textColor, fontWeight: 800, fontSize: fontSize.label - 2, fontFamily: displayFont, padding: "14px 16px", borderRadius: radius.cell, backgroundColor: surfaceWashForTheme(theme), borderLeft: `4px solid ${accentColor}` }}>
                {row.label}
              </div>
              {row.values.map((value, cIdx) => (
                <div key={cIdx} style={{ ...rowStyle, color: textColor, fontSize: fontSize.caption, fontFamily: bodyFont, textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {value}
                </div>
              ))}
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
