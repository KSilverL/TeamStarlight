import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { geoMercator, geoPath } from "d3-geo";
import type { MapSlide as MapSlideProps } from "../types";
import { loadCountryFeature, lonLatToBasemapPx } from "../map/geo";
import { textColorForTheme, type Theme } from "./theme";
import { fadeIn } from "../design/animations";
import { SlideHeadline } from "../design/components";
import { displayFont } from "../design/fonts";
import { fontSize, radius } from "../design/tokens";

const PIN_START = 15; // frame the first pin drops
const PIN_STAGGER = 12; // frames between consecutive pins

export const MapSlide: React.FC<{
  slide: MapSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: Theme;
}> = ({ slide, accentColor, secondaryColor, primaryColor, theme }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const textColor = textColorForTheme(theme);

  // Basemap mode only when assets.py resolved a static-map image AND its
  // center/zoom — pins are projected with the identical slippy-map math the
  // Python side used to request the image, so they land on the right cities.
  const hasBasemap =
    slide.basemapLocalPath != null && slide.basemapCenter != null && slide.basemapZoom != null;

  const country = hasBasemap ? null : loadCountryFeature(slide.region);

  let projectPin: (lon: number, lat: number) => { x: number; y: number };
  let outlinePathD: string | null = null;

  if (hasBasemap) {
    const [centerLon, centerLat] = slide.basemapCenter as [number, number];
    const zoom = slide.basemapZoom as number;
    projectPin = (lon, lat) => lonLatToBasemapPx(lon, lat, centerLon, centerLat, zoom, width, height);
  } else {
    // Fit either the country outline or — when the region code has no
    // geometry (see regionIndex.ts quirks) — the pins' own bounding box.
    const fitTarget =
      country ??
      ({
        type: "MultiPoint",
        coordinates: slide.pins.map((p) => [p.lon, p.lat]),
      } as const);
    const projection = geoMercator().fitExtent(
      [
        [width * 0.08, height * 0.16],
        [width * 0.92, height * 0.84],
      ],
      fitTarget as never,
    );
    // A single pin (or identical pins) gives fitExtent a zero-area target and
    // an Infinity scale — pull back to a sane city-level scale at that point.
    if (!Number.isFinite(projection.scale())) {
      projection.center([slide.pins[0].lon, slide.pins[0].lat]).scale(8000).translate([width / 2, height / 2]);
    }
    projectPin = (lon, lat) => {
      const p = projection([lon, lat]) ?? [width / 2, height / 2];
      return { x: p[0], y: p[1] };
    };
    if (country) {
      outlinePathD = geoPath(projection)(country as never);
    }
  }

  const outlineOpacity = fadeIn(frame, { frames: 20 });
  const headlineOpacity = fadeIn(frame, { frames: 12 });
  const positions = slide.pins.map((p) => projectPin(p.lon, p.lat));

  // journey variant: a route line draws through the pins in order BEFORE they
  // drop, so pins are staggered later to let the route lead. The polyline uses
  // strokeDasharray/offset to "draw on" frame-deterministically.
  const isJourney = (slide.variant ?? "pins") === "journey" && positions.length > 1;
  const routeDrawFrames = 30;
  const routePoints = positions.map((p) => `${p.x},${p.y}`).join(" ");
  const routeLen = positions.reduce((sum, p, i) => {
    if (i === 0) return 0;
    const q = positions[i - 1];
    return sum + Math.hypot(p.x - q.x, p.y - q.y);
  }, 0);
  const routeProgress = isJourney ? fadeIn(frame, { frames: routeDrawFrames }) : 1;
  const pinStart = isJourney ? PIN_START + routeDrawFrames : PIN_START;

  return (
    <AbsoluteFill style={{ backgroundColor: primaryColor }}>
      {hasBasemap && (
        <>
          {/* basemapLocalPath is job-directory-relative (e.g. "maps/2.png"), served
              via the render's --public-dir, same mechanics as HookSlide images. */}
          <Img
            src={staticFile(slide.basemapLocalPath as string)}
            style={{ position: "absolute", width: "100%", height: "100%", objectFit: "cover" }}
          />
          {/* Tint keeps the text legible over an arbitrary basemap. A light theme
              gets a much fainter wash — its basemap (osm-bright) is already
              near-white, and primaryColor is near-white too, so 0.35 would fog
              the streets the pins are supposed to sit on. */}
          <AbsoluteFill style={{ backgroundColor: primaryColor, opacity: theme === "light" ? 0.12 : 0.35 }} />
        </>
      )}
      {outlinePathD && (
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: outlineOpacity }}>
          <path d={outlinePathD} fill={secondaryColor} fillOpacity={0.16} stroke={accentColor} strokeWidth={3} />
        </svg>
      )}
      {isJourney && (
        <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
          <polyline
            points={routePoints}
            fill="none"
            stroke={accentColor}
            strokeWidth={4}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray={routeLen}
            strokeDashoffset={routeLen * (1 - routeProgress)}
            opacity={0.9}
          />
        </svg>
      )}
      {slide.headline && (
        <SlideHeadline color={textColor} opacity={headlineOpacity}>
          {slide.headline}
        </SlideHeadline>
      )}
      {slide.pins.map((pin, i) => {
        const { x, y } = positions[i];
        // Push the card away from the nearest OTHER pin vertically — two nearby
        // venues (a few hundred metres apart in a city) otherwise put their cards
        // on the same band and overlap. A single pin keeps the centered card.
        let cardShift = "translateY(-50%)";
        if (positions.length > 1) {
          let nearest = 0;
          let best = Infinity;
          positions.forEach((q, j) => {
            if (j === i) return;
            const d = (q.x - x) ** 2 + (q.y - y) ** 2;
            if (d < best) {
              best = d;
              nearest = j;
            }
          });
          cardShift = positions[nearest].y >= y
            ? "translateY(calc(-100% + 6px))" // neighbour below → card above the pin
            : "translateY(-6px)"; // neighbour above → card below the pin
        }
        const start = pinStart + i * PIN_STAGGER;
        const drop = spring({ frame: Math.max(0, frame - start), fps, config: { damping: 12, mass: 0.5 } });
        const cardOpacity = interpolate(frame, [start + 8, start + 16], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        // Card sits on whichever side of the pin has more canvas horizontally.
        const cardOnRight = x < width / 2;
        return (
          <React.Fragment key={i}>
            <div
              style={{
                position: "absolute",
                left: x,
                top: y,
                transform: `translate(-50%, -50%) scale(${drop})`,
                width: 26,
                height: 26,
                borderRadius: "50%",
                backgroundColor: accentColor,
                border: "5px solid white",
                boxShadow: "0 2px 10px rgba(0,0,0,0.45)",
              }}
            />
            <div
              style={{
                position: "absolute",
                left: cardOnRight ? x + 26 : undefined,
                right: cardOnRight ? undefined : width - x + 26,
                top: y,
                transform: cardShift,
                opacity: cardOpacity,
                backgroundColor: primaryColor,
                borderRadius: radius.cell,
                padding: "10px 16px",
                boxShadow: "0 2px 12px rgba(0,0,0,0.35)",
                maxWidth: width * 0.36,
              }}
            >
              <div style={{ color: textColor, fontSize: 34, fontWeight: 800, fontFamily: displayFont, lineHeight: 1.15 }}>{pin.label}</div>
              {pin.stats.map((stat, j) => (
                <div key={j} style={{ color: textColor, opacity: 0.85, fontSize: fontSize.caption + 2, marginTop: 4 }}>
                  {stat}
                </div>
              ))}
            </div>
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};
