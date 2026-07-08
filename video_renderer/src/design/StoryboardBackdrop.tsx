// The storyboard-wide atmosphere drawn ONCE over every slide (Composition.tsx),
// selected by RenderableStoryboard.backgroundStyle. "solid" renders nothing so
// pre-variant storyboards are pixel-identical. Because this layers OVER the slides
// (they paint opaque primaryColor), the treatments are deliberately faint and
// corner-weighted — gradient/orbs sit toward the edges, grid is a whisper — so
// centred headlines/charts stay clean. Slides may still set a stronger local bg.

import React from "react";
import { AbsoluteFill } from "remotion";
import { BackdropOrbs, GradientWash, GridPattern } from "./backdrops";
import { textColorForTheme, type Theme } from "../slides/theme";

export type BackgroundStyle = "solid" | "gradient" | "aurora" | "grid";

export const StoryboardBackdrop: React.FC<{
  style?: BackgroundStyle;
  accentColor: string;
  secondaryColor: string;
  theme?: Theme;
}> = ({ style, accentColor, secondaryColor, theme }) => {
  switch (style) {
    case "gradient":
      return <GradientWash accentColor={accentColor} secondaryColor={secondaryColor} strength={0.1} />;
    case "aurora":
      return <BackdropOrbs accentColor={accentColor} secondaryColor={secondaryColor} opacity={0.12} />;
    case "grid":
      return <GridPattern color={textColorForTheme(theme)} opacity={0.05} />;
    case "solid":
    default:
      return <AbsoluteFill />;
  }
};
