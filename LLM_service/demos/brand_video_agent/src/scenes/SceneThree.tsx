import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

export interface SceneThreeProps {
  brandName?: string;
  headline?: string;
  subtext?: string;
  ctaLabel?: string;
  contact?: string;
  primaryColor?: string;
  secondaryColor?: string;
  accentColor?: string;
}

// ── Pulsing ring around the CTA button ──────────────────────────────────────
const PulseRing: React.FC<{
  frame: number;
  delay: number;
  cx: number;
  cy: number;
  baseR: number;
  color: string;
}> = ({ frame, delay, cx, cy, baseR, color }) => {
  const localFrame = frame - delay;
  const CYCLE = 60; // one pulse every 60 frames
  const t = ((localFrame % CYCLE) + CYCLE) % CYCLE;

  const r = interpolate(t, [0, CYCLE], [baseR, baseR + 90], {
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(t, [0, CYCLE * 0.5, CYCLE], [0.6, 0.2, 0], {
    extrapolateRight: "clamp",
  });

  if (localFrame < 0) return null;

  return (
    <circle
      cx={cx}
      cy={cy}
      r={r}
      fill="none"
      stroke={color}
      strokeWidth={2}
      opacity={opacity}
    />
  );
};

// ── Scene 3 ──────────────────────────────────────────────────────────────────
export const SceneThree: React.FC<SceneThreeProps> = ({
  brandName = "APEX",
  headline = "Ready to Elevate?",
  subtext = "Join thousands of brands already growing with us.",
  ctaLabel = "Get Started Today",
  contact = "@apexbrand · apexbrand.com",
  primaryColor = "#0f0f1a",
  secondaryColor = "#6c63ff",
  accentColor = "#ff6584",
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // ── Scene fade in ────────────────────────────────────────────
  const bgOpacity = interpolate(frame, [0, 16], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Headline: splits into two words animating in sequence ────
  const headlineY = interpolate(frame, [10, 38], [60, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  const headlineOpacity = interpolate(frame, [10, 38], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Subtext fades in below headline ─────────────────────────
  const subtextOpacity = interpolate(frame, [38, 60], [0, 1], {
    extrapolateRight: "clamp",
  });
  const subtextY = interpolate(frame, [38, 60], [20, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // ── CTA button springs in ────────────────────────────────────
  const btnScale = spring({
    frame: frame - 55,
    fps,
    config: { damping: 10, stiffness: 110, mass: 0.9 },
  });
  const btnOpacity = interpolate(frame, [55, 72], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Divider line ─────────────────────────────────────────────
  const dividerW = interpolate(frame, [80, 100], [0, width * 0.5], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // ── Contact / handle fades in ────────────────────────────────
  const contactOpacity = interpolate(frame, [88, 108], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Brand mark callback: small logo returns bottom-centre ────
  const logoScale = spring({
    frame: frame - 98,
    fps,
    config: { damping: 14, stiffness: 90 },
  });

  // Button geometry
  const btnW = width * 0.72;
  const btnH = 110;
  const btnR = btnH / 2;

  // Pulse rings emit from button centre
  const btnCY = height * 0.62;
  const btnCX = width / 2;

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: primaryColor,
        overflow: "hidden",
        position: "relative",
        opacity: bgOpacity,
      }}
    >
      {/* ── Background blobs ── */}
      <div
        style={{
          position: "absolute",
          top: height * 0.3,
          right: -width * 0.35,
          width: width * 0.85,
          height: width * 0.85,
          borderRadius: "50%",
          background: secondaryColor,
          opacity: 0.07,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: -height * 0.1,
          left: -width * 0.2,
          width: width * 0.6,
          height: width * 0.6,
          borderRadius: "50%",
          background: accentColor,
          opacity: 0.06,
          pointerEvents: "none",
        }}
      />

      {/* ── SVG layer: pulse rings ── */}
      <svg
        style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none" }}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
      >
        <PulseRing
          frame={frame}
          delay={60}
          cx={btnCX}
          cy={btnCY}
          baseR={btnW / 2}
          color={accentColor}
        />
        <PulseRing
          frame={frame}
          delay={90}
          cx={btnCX}
          cy={btnCY}
          baseR={btnW / 2}
          color={secondaryColor}
        />
      </svg>

      {/* ── Headline ── */}
      <div
        style={{
          position: "absolute",
          top: height * 0.16,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 20,
          opacity: headlineOpacity,
          transform: `translateY(${headlineY}px)`,
          padding: "0 60px",
        }}
      >
        <div
          style={{
            fontSize: Math.round(width * 0.115),
            fontFamily: "Georgia, serif",
            fontWeight: "bold",
            color: "#ffffff",
            textAlign: "center",
            lineHeight: 1.1,
          }}
        >
          {headline}
        </div>
      </div>

      {/* ── Subtext ── */}
      <div
        style={{
          position: "absolute",
          top: height * 0.38,
          left: 0,
          right: 0,
          padding: "0 72px",
          opacity: subtextOpacity,
          transform: `translateY(${subtextY}px)`,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontSize: Math.round(width * 0.038),
            fontFamily: "system-ui, sans-serif",
            color: "rgba(255,255,255,0.65)",
            lineHeight: 1.55,
            letterSpacing: "0.04em",
          }}
        >
          {subtext}
        </div>
      </div>

      {/* ── CTA Button ── */}
      <div
        style={{
          position: "absolute",
          top: btnCY - btnH / 2,
          left: (width - btnW) / 2,
          width: btnW,
          height: btnH,
          borderRadius: btnR,
          background: `linear-gradient(135deg, ${secondaryColor}, ${accentColor})`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: btnOpacity,
          transform: `scale(${btnScale})`,
          boxShadow: `0 0 ${Math.round(width * 0.06)}px ${secondaryColor}55`,
        }}
      >
        <div
          style={{
            fontSize: Math.round(width * 0.044),
            fontFamily: "system-ui, sans-serif",
            fontWeight: "bold",
            color: "#ffffff",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          {ctaLabel}
        </div>
      </div>

      {/* ── Divider + contact ── */}
      <div
        style={{
          position: "absolute",
          top: height * 0.76,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 28,
        }}
      >
        <div
          style={{
            width: dividerW,
            height: 1,
            backgroundColor: `rgba(255,255,255,0.15)`,
          }}
        />
        <div
          style={{
            opacity: contactOpacity,
            fontSize: Math.round(width * 0.034),
            fontFamily: "system-ui, sans-serif",
            color: "rgba(255,255,255,0.45)",
            letterSpacing: "0.08em",
          }}
        >
          {contact}
        </div>
      </div>

      {/* ── Brand mark callback (small hex logo) ── */}
      <div
        style={{
          position: "absolute",
          bottom: height * 0.055,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          transform: `scale(${logoScale})`,
        }}
      >
        <svg width={48} height={48} viewBox="0 0 120 120">
          <polygon
            points="60,10 105,35 105,85 60,110 15,85 15,35"
            fill="none"
            stroke={`${secondaryColor}88`}
            strokeWidth={3}
          />
          <text
            x={60}
            y={68}
            textAnchor="middle"
            fill={`${secondaryColor}88`}
            fontSize={36}
            fontFamily="Georgia, serif"
            fontWeight="bold"
          >
            {brandName[0]}
          </text>
        </svg>
      </div>
    </div>
  );
};
