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

export interface HookSlide {
  type: "hook";
  headline: string;
  subtext?: string;
  imageLocalPath?: string;
  shape: "circle" | "blob" | "hex";
  durationFrames: number;
}

export interface CounterStatSlide {
  type: "counter_stat";
  sectionLabel?: string;
  stats: StatItem[];
  durationFrames: number;
}

export interface ResolvedImage {
  query: string;
  localPath?: string;
}

export interface CollageSlide {
  type: "collage";
  headline?: string;
  layout: "grid" | "scatter" | "stack";
  resolvedImages: ResolvedImage[];
  durationFrames: number;
}

export interface OutroSlide {
  type: "outro";
  brandName: string;
  ctaLabel: string;
  contact?: string;
  durationFrames: number;
}

// ── Phase 2: data/chart slides — all values are LLM-authored, not fetched live ──

export interface PieSlice {
  label: string;
  value: number;
}

export interface PieChartSlide {
  type: "pie_chart";
  headline?: string;
  slices: PieSlice[];
  calloutText?: string;
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
  durationFrames: number;
}

export interface NodeDiagramSlide {
  type: "node_diagram";
  headline?: string;
  nodes: string[];
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
  | GeneratedSlide;

export interface RenderableStoryboard {
  brandName: string;
  primaryColor: string;
  secondaryColor: string;
  accentColor: string;
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
