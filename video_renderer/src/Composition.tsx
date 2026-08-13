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

// Remotion's `volume` is a linear multiplier, not dB: x = 10^(dB/20).
// -18dB ≈ 0.13 — the bed sits under a voiceover, matching CLAUDE.md's
// "-18dB under any voiceover" spec.
const MUSIC_VOLUME_UNDER_VO = 0.13;
// -9dB ≈ 0.35 — a music-only video has nothing to leave headroom for, and at
// 0.13 it reads as near-silent. Music carries the video on its own here.
const MUSIC_VOLUME_SOLO = 0.35;

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
  voiceoverSlidePaths,
}) => {
  const activeTransition = transition ?? "none";
  const presentation = presentationFor(activeTransition, height > width);
  const timing = linearTiming({ durationInFrames: TRANSITION_OVERLAP_FRAMES });
  // Per-slide narration (slide-synced) takes precedence: when Python resolved one clip
  // per slide, each plays INSIDE its own sequence below. The global whole-video track is
  // the fallback (caller-supplied script or a legacy storyboard), used only when there
  // are no per-slide paths.
  const hasSlideVoiceover = Boolean(voiceoverSlidePaths && voiceoverSlidePaths.length > 0);
  // Deliberately NOT hasSlideVoiceover: that one asks "did Python resolve per-slide
  // clips?" (so the global track is skipped), and an all-null array still answers yes.
  // Picking the music level needs the different question "is any voice actually
  // audible?" — a storyboard whose slides all have narration: null is a music-only
  // video and should be mixed like one.
  const hasAnyVoiceover =
    Boolean(voiceoverLocalPath) || Boolean(voiceoverSlidePaths?.some(Boolean));

  return (
    <>
      {/* The two tracks are mixed as-is with no per-frame ducking: the music level is
          simply chosen up-front for the video it's in — quiet enough to sit under a
          voiceover, or loud enough to carry a video that has none. */}
      {musicLocalPath && (
        <Audio
          src={staticFile(musicLocalPath)}
          volume={hasAnyVoiceover ? MUSIC_VOLUME_UNDER_VO : MUSIC_VOLUME_SOLO}
        />
      )}
      {/* Voiceover plays at full volume (Remotion default). */}
      {!hasSlideVoiceover && voiceoverLocalPath && <Audio src={staticFile(voiceoverLocalPath)} />}
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
          // This slide's narration clip (slide-synced): placed inside the sequence so
          // Remotion positions it at the slide's start and clips it to the slide — which
          // Python already stretched to fit the line. null/absent => this slide is silent.
          const slideVoiceover = voiceoverSlidePaths?.[i] ?? null;
          const sequence = (
            <TransitionSeries.Sequence key={`seq-${i}`} durationInFrames={slide.durationFrames}>
              {slideVoiceover && <Audio src={staticFile(slideVoiceover)} />}
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
