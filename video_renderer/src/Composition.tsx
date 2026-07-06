import React from "react";
import { Audio, Series, staticFile } from "remotion";
import { resolveSlideComponent } from "./registry";
import type { RenderableStoryboard } from "./types";

// -18dB ≈ 10^(-18/20) ≈ 0.13 linear gain (Remotion's `volume` is a linear
// multiplier, not dB) — keeps headroom under a future voiceover track without
// retuning later, matching CLAUDE.md's "-18dB under any voiceover" spec.
const MUSIC_VOLUME = 0.13;

export const StoryboardRenderer: React.FC<RenderableStoryboard> = ({
  primaryColor,
  secondaryColor,
  accentColor,
  slides,
  musicLocalPath,
  voiceoverLocalPath,
}) => {
  return (
    <>
      {musicLocalPath && <Audio src={staticFile(musicLocalPath)} volume={MUSIC_VOLUME} />}
      {/* Full volume (Remotion default) — MUSIC_VOLUME above was chosen specifically
          to leave headroom under a narration track, so no ducking logic is needed
          here: the two tracks are just mixed as-is. */}
      {voiceoverLocalPath && <Audio src={staticFile(voiceoverLocalPath)} />}
      <Series>
        {slides.map((slide, i) => {
          // Fixed types resolve against SLIDE_REGISTRY up-front (see registry.ts);
          // a `generated` slide resolves against GENERATED_REGISTRY, populated by
          // this job's entry point before registerRoot(). Either way, an
          // unresolved slide is a server-side bug (codegen.py's fallback means the
          // storyboard should never reference a componentName that failed to
          // generate), not a case to silently skip.
          const SlideComponent = resolveSlideComponent(slide);
          if (!SlideComponent) {
            throw new Error(
              `no component resolved for slide ${i} (type=${slide.type}` +
                (slide.type === "generated" ? `, componentName=${slide.componentName}` : "") +
                ")",
            );
          }
          return (
            <Series.Sequence key={i} durationInFrames={slide.durationFrames}>
              <SlideComponent
                slide={slide as any}
                accentColor={accentColor}
                secondaryColor={secondaryColor}
                primaryColor={primaryColor}
              />
            </Series.Sequence>
          );
        })}
      </Series>
    </>
  );
};
