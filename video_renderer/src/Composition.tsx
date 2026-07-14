import React from "react";
import { Audio, staticFile } from "remotion";
import { TransitionSeries, linearTiming, type TransitionPresentation } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { wipe } from "@remotion/transitions/wipe";
import { resolveSlideComponent } from "./registry";
import type { RenderableStoryboard } from "./types";
import { StoryboardBackdrop } from "./design/StoryboardBackdrop";
import { TRANSITION_OVERLAP_FRAMES } from "./metadata";

// -18dB ≈ 10^(-18/20) ≈ 0.13 linear gain (Remotion's `volume` is a linear
// multiplier, not dB) — keeps headroom under a future voiceover track without
// retuning later, matching CLAUDE.md's "-18dB under any voiceover" spec.
const MUSIC_VOLUME = 0.13;

// The presentation for a storyboard-wide transition. `vertical` (9:16) pushes/wipes
// along the tall axis; `horizontal` (16:9) along the wide axis — so motion always
// runs the long way. "none" is handled by the caller (no <Transition> is emitted).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const presentationFor = (transition: string, vertical: boolean): TransitionPresentation<any> | null => {
  switch (transition) {
    case "fade":
      return fade();
    case "slide":
      return slide({ direction: vertical ? "from-bottom" : "from-left" });
    case "wipe":
      return wipe({ direction: vertical ? "from-bottom" : "from-left" });
    default:
      return null;
  }
};

export const StoryboardRenderer: React.FC<RenderableStoryboard> = ({
  theme,
  primaryColor,
  secondaryColor,
  accentColor,
  backgroundStyle,
  transition,
  width,
  height,
  slides,
  musicLocalPath,
  voiceoverLocalPath,
}) => {
  const activeTransition = transition ?? "none";
  const presentation = presentationFor(activeTransition, height > width);
  const timing = linearTiming({ durationInFrames: TRANSITION_OVERLAP_FRAMES });

  return (
    <>
      {musicLocalPath && <Audio src={staticFile(musicLocalPath)} volume={MUSIC_VOLUME} />}
      {/* Full volume (Remotion default) — MUSIC_VOLUME above was chosen specifically
          to leave headroom under a narration track, so no ducking logic is needed
          here: the two tracks are just mixed as-is. */}
      {voiceoverLocalPath && <Audio src={staticFile(voiceoverLocalPath)} />}
      {/* TransitionSeries with no <Transition> children is a plain hard-cut series,
          identical to the old <Series>; a <Transition> is interleaved between slides
          only when `transition` is active, overlapping them by TRANSITION_OVERLAP_FRAMES
          (metadata.ts subtracts the same from the total). */}
      <TransitionSeries>
        {slides.flatMap((slide, i) => {
          // Fixed types resolve against SLIDE_REGISTRY up-front (see registry.ts);
          // a `generated` slide resolves against GENERATED_REGISTRY, populated by
          // this job's entry point before registerRoot(). Either way, an unresolved
          // slide is a server-side bug (codegen.py's fallback means the storyboard
          // should never reference a componentName that failed to generate).
          const SlideComponent = resolveSlideComponent(slide);
          if (!SlideComponent) {
            throw new Error(
              `no component resolved for slide ${i} (type=${slide.type}` +
                (slide.type === "generated" ? `, componentName=${slide.componentName}` : "") +
                ")",
            );
          }
          const sequence = (
            <TransitionSeries.Sequence key={`seq-${i}`} durationInFrames={slide.durationFrames}>
              <SlideComponent
                slide={slide as any}
                accentColor={accentColor}
                secondaryColor={secondaryColor}
                primaryColor={primaryColor}
                theme={theme ?? "dark"}
              />
            </TransitionSeries.Sequence>
          );
          // Interleave a transition before every slide except the first.
          if (i > 0 && presentation) {
            return [
              <TransitionSeries.Transition key={`trans-${i}`} timing={timing} presentation={presentation} />,
              sequence,
            ];
          }
          return [sequence];
        })}
      </TransitionSeries>
      {/* Storyboard-wide atmosphere, drawn ONCE over every slide to tie the video
          together. "solid"/undefined renders nothing, so pre-variant storyboards are
          pixel-identical. Deliberately subtle + corner-weighted (see StoryboardBackdrop)
          so centred content stays legible; slides may still set their own local bg. */}
      <StoryboardBackdrop
        style={backgroundStyle}
        accentColor={accentColor}
        secondaryColor={secondaryColor}
        theme={theme ?? "dark"}
      />
    </>
  );
};
