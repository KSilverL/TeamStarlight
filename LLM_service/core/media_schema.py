"""
Structured spec for the post-approval media producer (the "生成视频" idea, ported
from demos/brand_video_agent).

`BrandVideoProps` is the data structure an LLM produces from a brand brief — it
carries NO visual code, only the typed fields that drive a 12-second, 3-scene 9:16
video (brand identity → three stats → CTA). The Python service stops here: the
actual Remotion / Chromium render stays out of process (see demos/brand_video_agent),
so this module has no rendering dependency.

It lives in `core/` (the shared layer) so both `workflow/messages.py` (FinalDraft
carries it) and `core/services/*` (the LLM produces it) can import it without a
layering inversion. `LLMService.generate_video_props` returns this model's
`model_dump()` (a JSON-friendly dict), matching the dict-return style of the other
service methods.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator


class StatItem(BaseModel):
    """One stat/feature card shown in Scene 2."""

    value: str = Field(description="Short stat value, e.g. '10K+' or '99%'")
    label: str = Field(description="Stat label, e.g. 'Happy Clients'")
    icon: str = Field(description="A single unicode symbol, e.g. ★ ◆ ▲ ● ■ ✦")

    @field_validator("icon")
    @classmethod
    def icon_is_short(cls, v: str) -> str:
        # Accept any symbol the LLM picks — just cap length to keep prose out.
        return v.strip()[:2]


class BrandVideoProps(BaseModel):
    """The full prop set for the 3-scene brand video (drives a Remotion composition
    downstream — rendering is intentionally external to this service)."""

    brandName: str = Field(description="Short brand name, 1-2 words, ALL CAPS")
    tagline: str = Field(description="Brand tagline, 3-6 words")
    primaryColor: str = Field(description="Hex colour — dark background, e.g. '#0d0d1a'")
    secondaryColor: str = Field(description="Hex colour — main brand accent")
    accentColor: str = Field(description="Hex colour — complementary pop colour")
    sectionLabel: str = Field(description="Section header for Scene 2, e.g. 'Why Choose Us'")
    stats: List[StatItem] = Field(
        min_length=3, max_length=3,
        description="Exactly 3 key stats or features for Scene 2",
    )
    headline: str = Field(description="CTA headline for Scene 3, 3-5 words, ends with '?'")
    subtext: str = Field(description="Supporting sentence under the CTA headline, max 12 words")
    ctaLabel: str = Field(description="Button label, 2-4 words, action-oriented")
    contact: str = Field(description="Handle or URL shown at bottom, e.g. '@brand · brand.com'")
