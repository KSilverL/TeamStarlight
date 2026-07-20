import type { CalculateMetadataFunction } from "remotion";
import type { RenderableStoryboard } from "./types";

// Frames each active transition overlaps consecutive slides. KEEP IN SYNC WITH
// LLM_service/core/video_schema.py TRANSITION_OVERLAP_FRAMES and Composition.tsx's
// <TransitionSeries.Transition> timing() — the Python side sizes music/voiceover
// against the same total, so a mismatch would let audio run past the final frame.
export const TRANSITION_OVERLAP_FRAMES = 12;

// The rendered length: sum of slide durations minus the overlap at each of the
// (n-1) boundaries when a transition is active (mirrors renderable_total_frames()
// in video_schema.py).
export const totalFrames = (props: RenderableStoryboard): number => {
  const sum = props.slides.reduce((total, slide) => total + slide.durationFrames, 0);
  const transition = props.transition ?? "none";
  if (transition !== "none" && props.slides.length > 1) {
    return sum - TRANSITION_OVERLAP_FRAMES * (props.slides.length - 1);
  }
  return sum;
};

// Python (LLM_service/core/video_schema.py) already resolved width/height (from
// the platform→aspect-ratio lookup) and clamped every slide's durationFrames
// before writing the --props JSON, so this just sums what's already there (less
// any transition overlap). One generic <Composition> serves every aspect ratio/
// duration this way — no need to register a separate composition per template.
export const resolveMetadata: CalculateMetadataFunction<RenderableStoryboard> = ({ props }) => {
  return {
    width: props.width,
    height: props.height,
    fps: props.fps,
    durationInFrames: Math.max(totalFrames(props), props.fps), // never render a zero/negative-length video
  };
};
