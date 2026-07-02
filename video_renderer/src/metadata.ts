import type { CalculateMetadataFunction } from "remotion";
import type { RenderableStoryboard } from "./types";

// Python (LLM_service/core/video_schema.py) already resolved width/height (from
// the platform→aspect-ratio lookup) and clamped every slide's durationFrames
// before writing the --props JSON, so this just sums what's already there. One
// generic <Composition> serves every aspect ratio/duration this way — no need
// to register a separate composition per template.
export const resolveMetadata: CalculateMetadataFunction<RenderableStoryboard> = ({ props }) => {
  const durationInFrames = props.slides.reduce((total, slide) => total + slide.durationFrames, 0);

  return {
    width: props.width,
    height: props.height,
    fps: props.fps,
    durationInFrames: Math.max(durationInFrames, props.fps), // never render a zero/negative-length video
  };
};
