// KEEP IN SYNC WITH: LLM_service/core/video_schema.py
//
// This file mirrors the Python discriminated-union slide schema. Every slide
// `type` literal here must have exactly one matching Pydantic model in
// video_schema.py and exactly one registry entry in registry.ts. Python is the
// source of truth (it's what the LLM is prompted against and what writes the
// --props JSON this renderer reads) — when adding a slide type, add the Python
// model + skill doc first, then mirror the shape here.
//
// By the time Remotion sees this JSON, Python has already fully resolved it:
// durations are concrete frame counts (no nulls/clamps left to apply), and
// collage slides carry `resolvedImages` (local file paths), never raw search
// queries or remote URLs.

export interface StatItem {
  value: string;
  label: string;
  icon: string;
}

// Per-slide background treatment; mirrors video_schema.BackgroundStyle.
export type BackgroundStyle = "solid" | "gradient" | "orbs" | "grid";

export interface HookSlide {
  type: "hook";
  headline: string;
  subtext?: string;
  kicker?: string;
  imageLocalPath?: string;
  shape: "circle" | "blob" | "hex";
  // variant/background carry a default in the Python render model (always emitted),
  // but are optional here so components stay robust to older/hand-written props —
  // each slide re-applies its own default via `?? "..."`.
  variant?: "spotlight" | "poster" | "split";
  background?: BackgroundStyle;
  durationFrames: number;
}

export interface CounterStatSlide {
  type: "counter_stat";
  sectionLabel?: string;
  stats: StatItem[];
  variant?: "cards" | "orbit" | "ticker";
  emphasisIndex?: number;
  durationFrames: number;
}

export interface ResolvedImage {
  query: string;
  localPath?: string;
}

export interface CollageSlide {
  type: "collage";
  headline?: string;
  layout: "grid" | "scatter" | "stack" | "filmstrip" | "polaroid";
  captions?: string[];
  resolvedImages: ResolvedImage[];
  durationFrames: number;
}

export interface OutroSlide {
  type: "outro";
  brandName: string;
  ctaLabel: string;
  contact?: string;
  tagline?: string;
  variant?: "badge" | "sweep";
  durationFrames: number;
}

// ── Phase 2: data/chart slides — all values are LLM-authored, not fetched live ──

export interface PieSlice {
  label: string;
  value: number;
}

// Named chart palette; mirrors video_schema.PaletteName. Consumed by
// design/palettes.ts paletteFor(), which defaults unknown names to "brand".
export type PaletteName = "brand" | "vivid" | "pastel" | "duotone" | "heat" | "ocean" | "mono";

export interface PieChartSlide {
  type: "pie_chart";
  headline?: string;
  slices: PieSlice[];
  calloutText?: string;
  variant?: "classic" | "donut" | "exploded";
  paletteName?: PaletteName;
  source?: string;
  durationFrames: number;
}

export interface ChartSeries {
  label: string;
  values: number[];
}

export interface LineChartSlide {
  type: "line_chart";
  headline?: string;
  xLabels: string[];
  series: ChartSeries[];
  variant?: "classic" | "area_glow" | "step_reveal";
  annotation?: string;
  paletteName?: PaletteName;
  source?: string;
  durationFrames: number;
}

export interface BarItem {
  label: string;
  value: number;
}

export interface BarChartSlide {
  type: "bar_chart";
  headline?: string;
  bars: BarItem[];
  variant?: "columns" | "race" | "lollipop";
  highlightIndex?: number;
  paletteName?: PaletteName;
  source?: string;
  durationFrames: number;
}

export interface NodeDiagramSlide {
  type: "node_diagram";
  headline?: string;
  nodes: string[];
  variant?: "chain" | "hub" | "steps";
  durationFrames: number;
}

export interface ComparisonRow {
  label: string;
  values: string[];
}

export interface ComparisonTableSlide {
  type: "comparison_table";
  headline?: string;
  columns: string[];
  rows: ComparisonRow[];
  variant?: "rows" | "versus" | "scorecard";
  highlightColumn?: number;
  durationFrames: number;
}

export interface MapPin {
  label: string;
  // The LLM's geocoding query ("Aviva Stadium, Dublin, Ireland"), already resolved
  // into lon/lat by assets.py's _geocode_map_pins — informational at render time.
  query?: string;
  lon: number; // WGS84 longitude, negative = west
  lat: number;
  stats: string[]; // 0-3 short lines, e.g. "Pop: 1.2M"
}

export interface MapSlide {
  type: "map";
  headline?: string;
  region: string; // ISO 3166-1 alpha-2, e.g. "IE" — resolved via map/regionIndex.ts
  pins: MapPin[];
  variant?: "pins" | "journey";
  // The three basemap fields are set together (or not at all) by assets.py's
  // Geoapify resolution; absent → the bundled vector map renders instead.
  // basemapLocalPath is job-relative ("maps/0.png"), served via --public-dir.
  basemapLocalPath?: string;
  basemapCenter?: [number, number]; // [lon, lat]
  basemapZoom?: number;
  durationFrames: number;
}

// ── Phase 3: bespoke, LLM-authored scene (autonomous video-agent plan) ──────
// Unlike the fixed types above, `generated` has no hand-written component in
// registry.ts's SLIDE_REGISTRY. `componentName` names a file under
// src/generated/<job_id>/ that a per-job entry point imports and registers via
// registry.ts's registerGeneratedSlide — see workflow/video/codegen.py.
export interface GeneratedSlide {
  type: "generated";
  componentName: string;
  data: Record<string, unknown>;
  durationFrames: number;
}

export type Slide =
  | HookSlide
  | CounterStatSlide
  | CollageSlide
  | OutroSlide
  | PieChartSlide
  | LineChartSlide
  | BarChartSlide
  | NodeDiagramSlide
  | ComparisonTableSlide
  | MapSlide
  | GeneratedSlide;

export interface RenderableStoryboard {
  brandName: string;
  // Drives per-slide text colour (see slides/theme.ts) and which Geoapify basemap
  // style Python fetched. Optional with a "dark" default so pre-theme props JSON
  // still renders identically.
  theme?: "dark" | "light";
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
  // Storyboard-wide backdrop behind every slide + the default chart palette.
  // Optional so pre-variant props JSON still renders identically.
  backgroundStyle?: "solid" | "gradient" | "aurora" | "grid";
  paletteName?: PaletteName;
  // Cross-slide transition; metadata.ts subtracts TRANSITION_OVERLAP_FRAMES per
  // boundary from the total when this isn't "none". Optional with a "none" default.
  transition?: "none" | "fade" | "slide" | "wipe";
  width: number;
  height: number;
  fps: number;
  slides: Slide[];
  // Job-relative path (e.g. "music.mp3"), resolved by workflow/video/music.py.
  // Absent/undefined when generation failed or was skipped — render stays silent.
  musicLocalPath?: string;
  // Job-relative path (e.g. "voiceover.mp3"), resolved by workflow/video/voiceover.py.
  // Absent/undefined when no narration was requested or synthesis failed.
  voiceoverLocalPath?: string;
  // Index signature so this satisfies Remotion's `Record<string, unknown>` props
  // constraint (CalculateMetadataFunction / Composition generics require it).
  [key: string]: unknown;
}
