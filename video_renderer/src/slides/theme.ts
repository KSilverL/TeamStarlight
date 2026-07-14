// Storyboard-wide theme → concrete colours, shared by every slide component.
// KEEP IN SYNC WITH: LLM_service/core/video_schema.py StoryboardSpec.theme — Python
// picks the Geoapify basemap style from the same value (assets.py), so a "light"
// storyboard gets a light basemap AND dark text from the one field.
export type Theme = "dark" | "light";

// Near-black instead of pure #000 (and pure white for dark) for softer contrast
// against the near-white/near-black primaryColor backgrounds the LLM is prompted
// to pick.
export const textColorForTheme = (theme?: Theme): string =>
  theme === "light" ? "#111827" : "#ffffff";

// Subtle card/panel wash over the primary background (e.g. CounterStatSlide's
// stat cards) — a white wash is invisible on a light background, so flip it.
export const surfaceWashForTheme = (theme?: Theme): string =>
  theme === "light" ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.06)";

// Recharts grid lines and axis strokes/ticks, matching the original dark-theme
// alphas (0.12 grid, 0.6 axis) so dark renders are pixel-identical.
export const chartGridForTheme = (theme?: Theme): string =>
  theme === "light" ? "rgba(0,0,0,0.12)" : "rgba(255,255,255,0.12)";
export const chartAxisForTheme = (theme?: Theme): string =>
  theme === "light" ? "rgba(0,0,0,0.6)" : "rgba(255,255,255,0.6)";

// Connector lines between diagram nodes (NodeDiagramSlide).
export const connectorForTheme = (theme?: Theme): string =>
  theme === "light" ? "rgba(0,0,0,0.3)" : "rgba(255,255,255,0.3)";
