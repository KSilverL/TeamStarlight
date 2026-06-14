import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

export interface SceneOneProps {
  brandName?: string;
  tagline?: string;
  primaryColor?: string;
  secondaryColor?: string;
  accentColor?: string;
}

export const SceneOne: React.FC<SceneOneProps> = ({
  brandName = "APEX",
  tagline = "Elevate Your Brand",
  primaryColor = "#0f0f1a",
  secondaryColor = "#6c63ff",
  accentColor = "#ff6584",
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // ── Background ──────────────────────────────────────────────
  const bgOpacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Logo hexagon: spring scale-in at frame 10 ────────────────
  const logoScale = spring({
    frame: frame - 10,
    fps,
    config: { damping: 14, stiffness: 90, mass: 1 },
  });
  const logoOpacity = interpolate(frame, [10, 28], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Ring that expands outward after logo settles ─────────────
  const ringScale = interpolate(frame, [32, 56], [0.6, 1.15], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const ringOpacity = interpolate(frame, [32, 52, 56], [0, 0.5, 0], {
    extrapolateRight: "clamp",
  });

  // ── Brand name: slides up from +50 px ───────────────────────
  const nameY = interpolate(frame, [36, 64], [50, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp),
  });
  const nameOpacity = interpolate(frame, [36, 64], [0, 1], {
    extrapolateRight: "clamp",
  });

  // ── Horizontal rule: draws left→right ────────────────────────
  const ruleWidth = interpolate(frame, [60, 85], [0, 140], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // ── Tagline: fades in below the rule ─────────────────────────
  const taglineOpacity = interpolate(frame, [72, 96], [0, 1], {
    extrapolateRight: "clamp",
  });
  const taglineY = interpolate(frame, [72, 96], [16, 0], {
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  // ── Accent dots pop in at the end ────────────────────────────
  const dotsScale = spring({
    frame: frame - 88,
    fps,
    config: { damping: 10, stiffness: 140 },
  });

  const cx = width / 2;
  const cy = height * 0.38; // logo sits at ~38% down

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: primaryColor,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        position: "relative",
        opacity: bgOpacity,
      }}
    >
      {/* ── Ambient background blobs ── */}
      <div
        style={{
          position: "absolute",
          top: -height * 0.22,
          right: -width * 0.3,
          width: width * 0.9,
          height: width * 0.9,
          borderRadius: "50%",
          background: secondaryColor,
          opacity: 0.07,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: -height * 0.15,
          left: -width * 0.25,
          width: width * 0.7,
          height: width * 0.7,
          borderRadius: "50%",
          background: accentColor,
          opacity: 0.06,
          pointerEvents: "none",
        }}
      />

      {/* ── SVG layer: logo + ring ── */}
      <svg
        style={{ position: "absolute", top: 0, left: 0 }}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
      >
        {/* Expanding ring pulse */}
        <circle
          cx={cx}
          cy={cy}
          r={130 * ringScale}
          fill="none"
          stroke={secondaryColor}
          strokeWidth={2}
          opacity={ringOpacity}
        />

        {/* Hexagon outline */}
        <g
          transform={`translate(${cx},${cy}) scale(${logoScale})`}
          opacity={logoOpacity}
        >
          <polygon
            points="0,-90 77.9,-45 77.9,45 0,90 -77.9,45 -77.9,-45"
            fill="none"
            stroke={secondaryColor}
            strokeWidth={3}
          />
          <polygon
            points="0,-60 52,-30 52,30 0,60 -52,30 -52,-30"
            fill={secondaryColor}
            opacity={0.18}
          />
          {/* Initial letter */}
          <text
            x={0}
            y={18}
            textAnchor="middle"
            fill={secondaryColor}
            fontSize={64}
            fontFamily="Georgia, serif"
            fontWeight="bold"
          >
            {brandName[0]}
          </text>
        </g>
      </svg>

      {/* ── Text content column ── */}
      <div
        style={{
          position: "absolute",
          top: cy + 120,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
        }}
      >
        {/* Brand name */}
        <div
          style={{
            opacity: nameOpacity,
            transform: `translateY(${nameY}px)`,
            fontSize: Math.round(width * 0.11),
            fontFamily: "Georgia, serif",
            fontWeight: "bold",
            color: "#ffffff",
            letterSpacing: "0.18em",
            textTransform: "uppercase",
          }}
        >
          {brandName}
        </div>

        {/* Horizontal rule */}
        <div
          style={{
            width: ruleWidth,
            height: 2,
            backgroundColor: accentColor,
            borderRadius: 1,
          }}
        />

        {/* Tagline */}
        <div
          style={{
            opacity: taglineOpacity,
            transform: `translateY(${taglineY}px)`,
            fontSize: Math.round(width * 0.04),
            fontFamily: "system-ui, sans-serif",
            color: "rgba(255,255,255,0.75)",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            textAlign: "center",
            padding: "0 48px",
          }}
        >
          {tagline}
        </div>

        {/* Accent dots */}
        <div
          style={{
            display: "flex",
            gap: 14,
            marginTop: 16,
            transform: `scale(${dotsScale})`,
          }}
        >
          {[accentColor, secondaryColor, accentColor].map((color, i) => (
            <div
              key={i}
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                backgroundColor: color,
                opacity: i === 1 ? 1 : 0.5,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
};
