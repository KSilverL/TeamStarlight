from pydantic import BaseModel, Field, field_validator


class StatItem(BaseModel):
    value: str = Field(description="Short stat value, e.g. '10K+' or '99%'")
    label: str = Field(description="Stat label, e.g. 'Happy Clients'")
    icon: str = Field(description="A single unicode symbol, e.g. ★ ◆ ▲ ● ■ ✦")

    @field_validator("icon")
    @classmethod
    def icon_is_short(cls, v: str) -> str:
        # Accept any symbol the LLM picks — just cap length to prevent prose leaking in
        return v.strip()[:2]


class BrandVideoProps(BaseModel):
    brandName: str = Field(description="Short brand name, 1-2 words, ALL CAPS")
    tagline: str = Field(description="Brand tagline, 3-6 words")
    primaryColor: str = Field(description="Hex colour — dark background, e.g. '#0d0d1a'")
    secondaryColor: str = Field(description="Hex colour — main brand accent")
    accentColor: str = Field(description="Hex colour — complementary pop colour")
    sectionLabel: str = Field(description="Section header for Scene 2, e.g. 'Why Choose Us'")
    stats: list[StatItem] = Field(
        min_length=3, max_length=3,
        description="Exactly 3 key stats or features for Scene 2"
    )
    headline: str = Field(description="CTA headline for Scene 3, 3-5 words, ends with '?'")
    subtext: str = Field(description="Supporting sentence under the CTA headline, max 12 words")
    ctaLabel: str = Field(description="Button label, 2-4 words, action-oriented")
    contact: str = Field(description="Handle or URL shown at bottom, e.g. '@brand · brand.com'")
