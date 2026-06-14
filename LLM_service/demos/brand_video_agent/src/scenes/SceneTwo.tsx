import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

export interface SceneTwoProps {
  sectionLabel?: string;
  stats?: Array<{ value: string; label: string; icon: string }>;
  primaryColor?: string;
  secondaryColor?: string;
  accentColor?: string;
}

const DEFAULT_STATS = [
  { value: "10K+", label: "Happy Clients", icon: "★" },
  { value: "99%", label: "Satisfaction Rate", icon: "◆" },
  { value: "5 YRS", label: "Industry Experience", icon: "▲" },
];

// ── Animated stat card ───────────────────────────────────────────────────────
const StatCard: React.FC<{
  stat: { value: string; label: string; icon: string };
  startFrame: number;
  width: number;
  secondaryColor: string;
  accentColor: string;
  fps: number;
}> = ({ stat, startFrame, width, secondaryColor, accentColor, fps }) => {
  const frame = useCurrentFrame();

  const slideX = interpolate(frame, [startFrame, startFrame + 28], [width * 0.6, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });

  const opacity = interpolate(frame, [startFrame, startFrame + 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const valueScale = spring({
    frame: frame - (startFrame + 20),
    fps,
    config: { damping: 12, stiffness: 100 },
  });

  const cardW = width * 0.8;

  return (
    <div
      style={{
        opacity,
        transform: `translateX(${slideX}px)`,
        width: cardW,
        display: "flex",
        alignItems: "center",
        gap: 32,
        backgroundColor: "rgba(255,255,255,0.04)",
        borderLeft: `4px solid ${secondaryColor}`,
        borderRadius: 12,
        padding: "36px 40px",
      }}
    >
      {/* Icon circle */}
      <div
        style={{
          width: 72,
          height: 72,
          borderRadius: "50%",
          backgroundColor: `${secondaryColor}22`,
          border: `2px solid ${secondaryColor}55`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 28,
          color: secondaryColor,
          flexShrink: 0,
        }}
      >
        {stat.icon}
      </div>

      {/* Text */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div
          style={{
            fontSize: 64,
            fontFamily: "Georgia, serif",
            fontWeight: "bold",
            color: "#ffffff",
            lineHeight: 1,
            transform: `scale(${valueScale})`,
            transformOrigin: "left center",
          }}
        >
          {stat.value}
        </div>
        <div
          style={{
            fontSize: 28,
            fontFamily: "system-ui, sans-serif",
            color: "rgba(255,255,255,0.6)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          {stat.label}
        </div>
      </div>
    </div>
  );
};

// ── Scene 2 ──────────────────────────────────────────────────────────────────
export const SceneTwo: React.FC<SceneTwoProps> = ({
  sectionLabel = "Why Choose Us",
  stats = DEFAULT_STATS,
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

  // ── Section label drops in from top ─────────────────────────
  const labelY = interpolate(frame, [8, 34], [-60, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const labelOpacity = interpolate(frame, [8, 34], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Accent line under label ──────────────────────────────────
  const lineW = interpolate(frame, [30, 50], [0, 80], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // Cards stagger: each starts 18 frames after the previous
  const CARD_START_FRAMES = [42, 60, 78];

  // ── Bottom divider ───────────────────────────────────────────
  const lastCard = CARD_START_FRAMES[CARD_START_FRAMES.length - 1];
  const dividerOpacity = interpolate(frame, [lastCard + 30, lastCard + 48], [0, 1], {
    extrapolateRight: "clamp",
  });
  const dividerScale = spring({
    frame: frame - (lastCard + 28),
    fps,
    config: { damping: 14, stiffness: 80 },
  });

  const topY = height * 0.14;
  const cardsTopY = topY + 120;
  const cardGap = (height * 0.6) / stats.length;

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
      {/* ── Background blobs (mirrored from scene 1) ── */}
      <div
        style={{
          position: "absolute",
          top: -height * 0.05,
          left: -width * 0.3,
          width: width * 0.8,
          height: width * 0.8,
          borderRadius: "50%",
          background: secondaryColor,
          opacity: 0.06,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: -height * 0.1,
          right: -width * 0.2,
          width: width * 0.65,
          height: width * 0.65,
          borderRadius: "50%",
          background: accentColor,
          opacity: 0.05,
          pointerEvents: "none",
        }}
      />

      {/* ── Section label ── */}
      <div
        style={{
          position: "absolute",
          top: topY,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 18,
          opacity: labelOpacity,
          transform: `translateY(${labelY}px)`,
        }}
      >
        <div
          style={{
            fontSize: Math.round(width * 0.042),
            fontFamily: "system-ui, sans-serif",
            color: accentColor,
            letterSpacing: "0.2em",
            textTransform: "uppercase",
          }}
        >
          {sectionLabel}
        </div>
        {/* Accent underline */}
        <div
          style={{
            width: lineW,
            height: 3,
            backgroundColor: accentColor,
            borderRadius: 2,
          }}
        />
      </div>

      {/* ── Stat cards ── */}
      <div
        style={{
          position: "absolute",
          top: cardsTopY,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: cardGap * 0.22,
        }}
      >
        {stats.map((stat, i) => (
          <StatCard
            key={i}
            stat={stat}
            startFrame={CARD_START_FRAMES[i] ?? CARD_START_FRAMES[0] + i * 18}
            width={width}
            secondaryColor={secondaryColor}
            accentColor={accentColor}
            fps={fps}
          />
        ))}
      </div>

      {/* ── Bottom flourish ── */}
      <div
        style={{
          position: "absolute",
          bottom: height * 0.07,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          opacity: dividerOpacity,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            transform: `scale(${dividerScale})`,
          }}
        >
          <div style={{ width: 60, height: 1, backgroundColor: `${secondaryColor}66` }} />
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              backgroundColor: secondaryColor,
            }}
          />
          <div style={{ width: 60, height: 1, backgroundColor: `${secondaryColor}66` }} />
        </div>
      </div>
    </div>
  );
};
