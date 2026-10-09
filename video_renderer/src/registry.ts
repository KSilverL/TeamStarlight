// KEEP IN SYNC WITH: LLM_service/core/video_schema.py (the Slide discriminator
// literals: "cold_open" | "hook" | "counter_stat" | "collage" | "statement"
// | "media_statement" | "outro"). Every
// literal there needs exactly one entry here, and vice versa. Parity IS checked
// cross-language, by test_slide_registry_ts_covers_every_slide_type in
// LLM_service/tests/test_contract_parity.py, which parses the object literal
// below — keep it as one `key: Component,` per line.
import React from "react";
import { BarChartSlide } from "./slides/BarChartSlide";
import { CollageSlide } from "./slides/CollageSlide";
import { ColdOpenSlide } from "./slides/ColdOpenSlide";
import { ComparisonTableSlide } from "./slides/ComparisonTableSlide";
import { CounterStatSlide } from "./slides/CounterStatSlide";
import { HookSlide } from "./slides/HookSlide";
import { LineChartSlide } from "./slides/LineChartSlide";
import { MapSlide } from "./slides/MapSlide";
import { NodeDiagramSlide } from "./slides/NodeDiagramSlide";
import { OutroSlide } from "./slides/OutroSlide";
import { MediaStatementSlide } from "./slides/MediaStatementSlide";
import { PieChartSlide } from "./slides/PieChartSlide";
import { StatementSlide } from "./slides/StatementSlide";
import type { Slide } from "./types";

// Each slide component's `slide` prop is narrowly typed to its own variant
// (see slides/*.tsx); the registry erases that to `any` so it can be indexed
// dynamically by Composition.tsx, which re-narrows per-instance via the
// discriminant before rendering. The per-component prop types are still the
// source of truth for each file in isolation.
type AnySlideComponent = React.FC<{
  slide: any;
  accentColor: string;
  secondaryColor: string;
  primaryColor: string;
  theme?: "dark" | "light";
}>;

// "generated" is intentionally absent here: it has no hand-written component.
// resolveSlideComponent() below resolves it instead, from GENERATED_REGISTRY.
export const SLIDE_REGISTRY: Record<Exclude<Slide["type"], "generated">, AnySlideComponent> = {
  cold_open: ColdOpenSlide,
  hook: HookSlide,
  counter_stat: CounterStatSlide,
  collage: CollageSlide,
  statement: StatementSlide,
  media_statement: MediaStatementSlide,
  outro: OutroSlide,
  pie_chart: PieChartSlide,
  line_chart: LineChartSlide,
  bar_chart: BarChartSlide,
  node_diagram: NodeDiagramSlide,
  comparison_table: ComparisonTableSlide,
  map: MapSlide,
};

// Populated at module-load time by a per-job entry point (src/generated/<job_id>/*),
// which imports its own bespoke component(s) and calls registerGeneratedSlide before
// registerRoot() — see workflow/video/codegen.py's _write_preview_entry for the
// preview-render analogue, and the real per-job storyboard entry point for the
// full-render analogue. Never populated statically; a `generated` slide with no
// matching entry is a server-side bug (codegen.py's fallback means the storyboard
// should never reference a componentName that wasn't successfully generated).
const GENERATED_REGISTRY: Record<string, AnySlideComponent> = {};

export function registerGeneratedSlide(componentName: string, component: AnySlideComponent): void {
  GENERATED_REGISTRY[componentName] = component;
}

export function resolveSlideComponent(slide: Slide): AnySlideComponent | undefined {
  if (slide.type === "generated") {
    return GENERATED_REGISTRY[slide.componentName];
  }
  return SLIDE_REGISTRY[slide.type];
}
