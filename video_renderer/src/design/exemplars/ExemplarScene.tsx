// A reference bespoke scene for the `generated`-slide codegen agent. It lives under
// src/ (two levels deep, exactly like a real src/generated/<job>/ component) so its
// import paths — "../../types", "../../design" — are byte-identical to what a
// generated file uses, and so the project typecheck keeps it compiling forever.
// LLM_service/core/services/azure.py reads this file at prompt-build time and embeds
// it verbatim as the few-shot example, so it must stay an EXEMPLARY, self-contained
// Remotion scene: content entirely from slide.data, every element entering with a
// staggered animation, numbers counting up, a layered backdrop, generous margins.

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { GeneratedSlide } from "../../types";
import {
  GradientWash,
  Kicker,
  SlideHeadline,
  accentGlow,
  bodyFont,
  countUp,
  displayFont,
  fadeIn,
  fontSize,
  radius,
  springEnter,
  stagger,
} from "../../design";

// A generated component receives exactly this prop shape (see registry.ts /
// Composition.tsx). Read all content from `slide.data`; never hard-code copy.
const ExemplarScene: React.FC<{
  slide: GeneratedSlide;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, secondaryColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Shape the data defensively — the brief's `data` is free-form JSON.
  const kicker = typeof slide.data.kicker === "string" ? slide.data.kicker : null;
  const headline = typeof slide.data.headline === "string" ? slide.data.headline : "";
  const items = Array.isArray(slide.data.items)
    ? (slide.data.items as Array<{ label?: unknown; value?: unknown }>)
    : [];
  const rows = items.map((it) => ({
    label: String(it.label ?? ""),
    value: Number(it.value ?? 0),
  }));
  const max = Math.max(1, ...rows.map((r) => r.value));

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {/* Layer 1 — backdrop */}
      <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} strength={0.22} />

      {/* Layer 2 — heading block, generous top margin */}
      <div style={{ position: "absolute", top: "10%", width: "100%", textAlign: "center" }}>
        {kicker && <Kicker color={accentColor}>{kicker}</Kicker>}
        <SlideHeadline color="#ffffff" top="0" size={fontSize.h1}>
          {headline}
        </SlideHeadline>
      </div>

      {/* Layer 3 — ranked bars, each staggered in, value counting up */}
      <div style={{ position: "absolute", top: "34%", left: "9%", width: "82%", display: "flex", flexDirection: "column", gap: 22 }}>
        {rows.map((row, i) => {
          const delay = stagger(i, 6);
          const grow = springEnter(frame, fps, { delay, damping: 18 });
          const isLeader = row.value === max;
          return (
            <div key={i} style={{ opacity: fadeIn(frame, { delay, frames: 8 }) }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ color: "#ffffff", fontSize: fontSize.body, fontFamily: bodyFont }}>{row.label}</span>
                <span style={{ color: "#ffffff", fontSize: fontSize.label, fontWeight: 800, fontFamily: displayFont }}>
                  {countUp(frame, row.value, { delay }).toLocaleString()}
                </span>
              </div>
              <div style={{ height: 26, borderRadius: radius.bar, backgroundColor: "rgba(255,255,255,0.08)" }}>
                <div
                  style={{
                    height: "100%",
                    width: `${(row.value / max) * 100 * grow}%`,
                    borderRadius: radius.bar,
                    backgroundColor: isLeader ? accentColor : secondaryColor,
                    boxShadow: isLeader ? accentGlow(accentColor, 20) : undefined,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export default ExemplarScene;
