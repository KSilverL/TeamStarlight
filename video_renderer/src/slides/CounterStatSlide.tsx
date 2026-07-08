import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import type { CounterStatSlide as CounterStatSlideProps, StatItem } from "../types";
import { surfaceWashForTheme, textColorForTheme, type Theme } from "./theme";
import { countUp, fadeIn, popScale, slideIn, springEnter, stagger } from "../design/animations";
import { accentGlow, fontSize, radius } from "../design/tokens";
import { bodyFont, displayFont } from "../design/fonts";

// A stat's display value: pure numbers count up, formatted values (e.g. "99%",
// "10K+") fade in as-is. A plain function of frame (not a hook) so variants can
// call it unconditionally in any branch.
const statValue = (frame: number, value: string, delay: number): string => {
  const numeric = Number(value.replace(/[^0-9.]/g, ""));
  const isPureNumber = !Number.isNaN(numeric) && /^[0-9.,]+$/.test(value.trim());
  return isPureNumber ? countUp(frame, numeric, { delay }).toLocaleString() : value;
};

const StatCard: React.FC<{ stat: StatItem; index: number; accentColor: string; theme?: Theme }> = ({
  stat,
  index,
  accentColor,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const delay = stagger(index, 8);
  const enter = slideIn(frame, fps, { delay, damping: 16, distance: 60 });
  const displayValue = statValue(frame, stat.value, delay);

  return (
    <div
      style={{
        ...enter,
        display: "flex",
        alignItems: "center",
        gap: 20,
        padding: "20px 28px",
        borderRadius: radius.card,
        backgroundColor: surfaceWashForTheme(theme),
        borderLeft: `4px solid ${accentColor}`,
      }}
    >
      <span style={{ fontSize: 36 }}>{stat.icon}</span>
      <div>
        <div style={{ color: textColorForTheme(theme), fontSize: fontSize.stat, fontWeight: 800, fontFamily: displayFont }}>{displayValue}</div>
        <div style={{ color: textColorForTheme(theme), opacity: 0.7, fontSize: fontSize.caption, fontFamily: bodyFont }}>{stat.label}</div>
      </div>
    </div>
  );
};

// One full-width row whose accent bar grows as the value counts up (ticker variant).
const TickerRow: React.FC<{ stat: StatItem; index: number; count: number; accentColor: string; theme?: Theme }> = ({
  stat,
  index,
  count,
  accentColor,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const delay = stagger(index, 10);
  const opacity = fadeIn(frame, { delay, frames: 10 });
  const grow = springEnter(frame, fps, { delay, damping: 18 });
  const displayValue = statValue(frame, stat.value, delay);
  const textColor = textColorForTheme(theme);

  return (
    <div style={{ opacity, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ color: textColor, fontSize: fontSize.body, fontFamily: bodyFont }}>
          {stat.icon} {stat.label}
        </span>
        <span style={{ color: textColor, fontSize: fontSize.stat, fontWeight: 800, fontFamily: displayFont }}>{displayValue}</span>
      </div>
      <div style={{ height: 10, borderRadius: 999, backgroundColor: surfaceWashForTheme(theme) }}>
        <div style={{ height: "100%", width: `${100 * (0.35 + 0.65 * (index + 1) / count) * grow}%`, borderRadius: 999, backgroundColor: accentColor }} />
      </div>
    </div>
  );
};

export const CounterStatSlide: React.FC<{ slide: CounterStatSlideProps; accentColor: string; primaryColor: string; theme?: Theme }> = ({
  slide,
  accentColor,
  primaryColor,
  theme,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const textColor = textColorForTheme(theme);
  const variant = slide.variant ?? "cards";
  const heroIndex = Math.min(slide.emphasisIndex ?? 0, slide.stats.length - 1);

  const sectionLabel = slide.sectionLabel ? (
    <h2 style={{ color: textColor, opacity: 0.85, fontSize: fontSize.body, fontFamily: displayFont, marginBottom: 8 }}>{slide.sectionLabel}</h2>
  ) : null;

  // ── orbit: hero stat huge in the centre, the rest arranged around it ──────
  if (variant === "orbit") {
    const hero = slide.stats[heroIndex];
    const others = slide.stats.filter((_, i) => i !== heroIndex);
    const heroValue = statValue(frame, hero.value, 6);
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        <div style={{ position: "absolute", top: "8%", width: "100%", textAlign: "center" }}>{sectionLabel}</div>
        <div style={{ textAlign: "center", transform: `scale(${springEnter(frame, fps, { damping: 12 })})` }}>
          <div style={{ fontSize: 44 }}>{hero.icon}</div>
          <div style={{ color: accentColor, fontSize: fontSize.display, fontWeight: 800, fontFamily: displayFont, textShadow: accentGlow(accentColor, 30), lineHeight: 1 }}>
            {heroValue}
          </div>
          <div style={{ color: textColor, opacity: 0.8, fontSize: fontSize.body, fontFamily: bodyFont }}>{hero.label}</div>
        </div>
        <div style={{ position: "absolute", bottom: "10%", display: "flex", gap: 40, justifyContent: "center", width: "90%" }}>
          {others.map((stat, i) => {
            const enter = popScale(frame, fps, { delay: stagger(i + 1, 8), damping: 14 });
            return (
              <div key={i} style={{ ...enter, textAlign: "center" }}>
                <div style={{ color: textColor, fontSize: fontSize.subhead, fontWeight: 800, fontFamily: displayFont }}>{stat.value}</div>
                <div style={{ color: textColor, opacity: 0.7, fontSize: fontSize.caption, fontFamily: bodyFont }}>{stat.label}</div>
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
    );
  }

  // ── ticker: full-width rows with growing accent bars ──────────────────────
  if (variant === "ticker") {
    return (
      <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 28, width: "82%" }}>
          {sectionLabel}
          {slide.stats.map((stat, i) => (
            <TickerRow key={i} stat={stat} index={i} count={slide.stats.length} accentColor={accentColor} theme={theme} />
          ))}
        </div>
      </AbsoluteFill>
    );
  }

  // ── cards (default): stacked stat cards ───────────────────────────────────
  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor, justifyContent: "center", alignItems: "center" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 24, width: "80%" }}>
        {sectionLabel}
        {slide.stats.map((stat, i) => (
          <StatCard key={i} stat={stat} index={i} accentColor={accentColor} theme={theme} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
