import React from "react";
import { AbsoluteFill, Series } from "remotion";
import { SceneOne } from "./scenes/SceneOne";
import { SceneTwo } from "./scenes/SceneTwo";
import { SceneThree } from "./scenes/SceneThree";
import { BrandProps } from "./types";

export const MyComposition: React.FC<BrandProps> = ({
  brandName,
  tagline,
  primaryColor,
  secondaryColor,
  accentColor,
  sectionLabel,
  stats,
  headline,
  subtext,
  ctaLabel,
  contact,
}) => {
  const palette = { primaryColor, secondaryColor, accentColor };

  return (
    <AbsoluteFill>
      <Series>
        <Series.Sequence durationInFrames={120}>
          <SceneOne brandName={brandName} tagline={tagline} {...palette} />
        </Series.Sequence>

        <Series.Sequence durationInFrames={120}>
          <SceneTwo
            sectionLabel={sectionLabel}
            stats={stats}
            {...palette}
          />
        </Series.Sequence>

        <Series.Sequence durationInFrames={120}>
          <SceneThree
            brandName={brandName}
            headline={headline}
            subtext={subtext}
            ctaLabel={ctaLabel}
            contact={contact}
            {...palette}
          />
        </Series.Sequence>
      </Series>
    </AbsoluteFill>
  );
};
