import React from "react";
import { Composition, registerRoot } from "remotion";
import { StoryboardRenderer } from "./Composition";
import { resolveMetadata } from "./metadata";
import type { RenderableStoryboard } from "./types";

const defaultProps: RenderableStoryboard = {
  brandName: "BRAND",
  primaryColor: "#0d1117",
  secondaryColor: "#2d4ed8",
  accentColor: "#f5c84c",
  width: 1080,
  height: 1920,
  fps: 30,
  slides: [
    { type: "hook", headline: "Sample Headline", shape: "circle", durationFrames: 90 },
    { type: "outro", brandName: "BRAND", ctaLabel: "Learn More", durationFrames: 90 },
  ],
};

const Root: React.FC = () => (
  <Composition
    id="StoryboardVideo"
    component={StoryboardRenderer}
    calculateMetadata={resolveMetadata}
    // Placeholders only — calculateMetadata overrides these on every real render.
    durationInFrames={180}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={defaultProps}
  />
);

registerRoot(Root);
