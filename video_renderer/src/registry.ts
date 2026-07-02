// KEEP IN SYNC WITH: LLM_service/core/video_schema.py (the Slide discriminator
// literals: "hook" | "counter_stat" | "collage" | "outro"). Every literal there
// needs exactly one entry here, and vice versa. Python-side parity is checked by
// LLM_service/tests/test_video_schema.py; there is no cross-language check, so
// when adding a slide type, update both files in the same change.
import React from "react";
import { BarChartSlide } from "./slides/BarChartSlide";
import { CollageSlide } from "./slides/CollageSlide";
import { ComparisonTableSlide } from "./slides/ComparisonTableSlide";
import { CounterStatSlide } from "./slides/CounterStatSlide";
import { HookSlide } from "./slides/HookSlide";
import { LineChartSlide } from "./slides/LineChartSlide";
import { NodeDiagramSlide } from "./slides/NodeDiagramSlide";
import { OutroSlide } from "./slides/OutroSlide";
import { PieChartSlide } from "./slides/PieChartSlide";
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
}>;

export const SLIDE_REGISTRY: Record<Slide["type"], AnySlideComponent> = {
  hook: HookSlide,
  counter_stat: CounterStatSlide,
  collage: CollageSlide,
  outro: OutroSlide,
  pie_chart: PieChartSlide,
  line_chart: LineChartSlide,
  bar_chart: BarChartSlide,
  node_diagram: NodeDiagramSlide,
  comparison_table: ComparisonTableSlide,
};
