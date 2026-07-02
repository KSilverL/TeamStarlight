import React from "react";
import { Audio, Series, staticFile } from "remotion";
import { SLIDE_REGISTRY } from "./registry";
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
}) => {
  return (
    <>
      {musicLocalPath && <Audio src={staticFile(musicLocalPath)} volume={MUSIC_VOLUME} />}
      <Series>
        {slides.map((slide, i) => {
          // SLIDE_REGISTRY[slide.type] is fixed up-front against the discriminator
          // literal set (see registry.ts), so a slide of an unknown type is a
          // server-side bug (the LLM only ever picks from the registry), not a
          // case to silently skip.
          const SlideComponent = SLIDE_REGISTRY[slide.type];
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
