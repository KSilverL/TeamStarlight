import type { Feature, FeatureCollection, Geometry } from "geojson";
import { feature } from "topojson-client";
import world from "world-atlas/countries-50m.json";
import { REGION_INDEX } from "./regionIndex";

// countries-50m (not 110m): at 110m resolution small countries like Ireland
// collapse to a shapeless blob, and single-country fits are this module's
// whole purpose. Converted TopoJSON→GeoJSON once at module load; ~800 KB of
// data, so keep this file the only importer.
const countries = feature(
  world as unknown as never,
  (world as unknown as { objects: { countries: never } }).objects.countries,
) as unknown as FeatureCollection<Geometry>;

export function loadCountryFeature(alpha2: string): Feature<Geometry> | null {
  const numeric = REGION_INDEX[alpha2.toUpperCase()];
  if (!numeric) return null;
  return countries.features.find((f) => String(f.id) === numeric) ?? null;
}

// Normalized (0..1) Web Mercator y for a latitude.
// KEEP IN SYNC WITH: LLM_service/workflow/video/assets.py `_mercator_y` — the
// Python side picks the basemap's center/zoom with this same formula, and the
// pins only land on the right cities if both sides project identically.
export function mercatorY(lat: number): number {
  const rad = (lat * Math.PI) / 180;
  return (1 - Math.log(Math.tan(Math.PI / 4 + rad / 2)) / Math.PI) / 2;
}

// Project lon/lat onto a static-map image of size width×height rendered at
// (centerLon, centerLat) and `zoom` — the standard slippy-map formula with a
// 256px world tile. Mirrors how Geoapify (and every Web Mercator tile server)
// places its center, so overlay pins align exactly with the basemap.
export function lonLatToBasemapPx(
  lon: number,
  lat: number,
  centerLon: number,
  centerLat: number,
  zoom: number,
  width: number,
  height: number,
): { x: number; y: number } {
  const worldSize = 256 * Math.pow(2, zoom);
  return {
    x: width / 2 + ((lon - centerLon) / 360) * worldSize,
    y: height / 2 + (mercatorY(lat) - mercatorY(centerLat)) * worldSize,
  };
}
