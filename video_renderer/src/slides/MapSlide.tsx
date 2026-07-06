import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { geoMercator, geoPath } from "d3-geo";
import type { MapSlide as MapSlideProps } from "../types";
import { loadCountryFeature, lonLatToBasemapPx } from "../map/geo";

const PIN_START = 15; // frame the first pin drops
const PIN_STAGGER = 12; // frames between consecutive pins

export const MapSlide: React.FC<{
  slide: MapSlideProps;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
}> = ({ slide, accentColor, secondaryColor, primaryColor }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

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

  const outlineOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const headlineOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

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
          {/* Tint keeps white labels legible over an arbitrary basemap. */}
          <AbsoluteFill style={{ backgroundColor: primaryColor, opacity: 0.35 }} />
        </>
      )}
      {outlinePathD && (
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: outlineOpacity }}>
          <path d={outlinePathD} fill={secondaryColor} fillOpacity={0.16} stroke={accentColor} strokeWidth={3} />
        </svg>
      )}
      {slide.headline && (
        <h2
          style={{
            position: "absolute",
            top: "6%",
            width: "100%",
            textAlign: "center",
            color: "white",
            fontSize: 40,
            fontWeight: 800,
            opacity: headlineOpacity,
            margin: 0,
          }}
        >
          {slide.headline}
        </h2>
      )}
      {slide.pins.map((pin, i) => {
        const { x, y } = projectPin(pin.lon, pin.lat);
        const start = PIN_START + i * PIN_STAGGER;
        const drop = spring({ frame: Math.max(0, frame - start), fps, config: { damping: 12, mass: 0.5 } });
        const cardOpacity = interpolate(frame, [start + 8, start + 16], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        // Card sits on whichever side of the pin has more canvas.
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
                transform: "translateY(-50%)",
                opacity: cardOpacity,
                backgroundColor: primaryColor,
                borderRadius: 12,
                padding: "10px 16px",
                boxShadow: "0 2px 12px rgba(0,0,0,0.35)",
                maxWidth: width * 0.36,
              }}
            >
              <div style={{ color: "white", fontSize: 34, fontWeight: 800, lineHeight: 1.15 }}>{pin.label}</div>
              {pin.stats.map((stat, j) => (
                <div key={j} style={{ color: "white", opacity: 0.85, fontSize: 22, marginTop: 4 }}>
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
