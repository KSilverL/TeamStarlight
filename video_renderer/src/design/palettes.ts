// Named colour-palette repository for data marks (chart slices, lines, bars,
// collage shapes). Every palette resolves through `paletteFor(...)`, which blends
// in the storyboard's brand colours where the palette calls for them — so a
// palette is a *recipe*, not a fixed list, and stays on-brand for any storyboard.
//
// "brand" (the default) reproduces the exact pre-palette behaviour every chart
// slide hardcoded: brand accent + secondary first, then the shared fallback ladder
// with brand-duplicates filtered out — so storyboards that never pick a palette
// render identically to before this module existed.

import type { Theme } from "../slides/theme";

export type PaletteName =
  | "brand"
  | "vivid"
  | "pastel"
  | "duotone"
  | "heat"
  | "ocean"
  | "mono";

export const PALETTE_NAMES: readonly PaletteName[] = [
  "brand", "vivid", "pastel", "duotone", "heat", "ocean", "mono",
] as const;

export interface BrandColors {
  accentColor: string;
  secondaryColor: string;
}

// The pre-module fallback ladder (PieChartSlide's SLICE_COLORS was the superset of
// LineChartSlide's LINE_COLORS and CollageSlide's SHAPE_COLORS).
const BRAND_FALLBACK = ["#f5c84c", "#2d4ed8", "#e2725b", "#34c98f", "#a06cd5", "#ff8966"];

// Saturated editorial set — high-energy briefs.
const VIVID = ["#ff5c5c", "#3b82f6", "#a3e635", "#8b5cf6", "#f59e0b", "#14b8a6"];

// Soft washes of the vivid hues — light themes, calm briefs.
const PASTEL = ["#fda4af", "#93c5fd", "#d9f99d", "#c4b5fd", "#fcd34d", "#99f6e4"];

// Sequential ember ramp — magnitude/intensity stories.
const HEAT = ["#fde68a", "#fbbf24", "#f97316", "#ea580c", "#dc2626", "#b91c1c"];

// Cool sequential — depth/scale/technology stories.
const OCEAN = ["#a5f3fc", "#67e8f9", "#38bdf8", "#0ea5e9", "#2563eb", "#1e3a8a"];

/** Normalize 3-digit hex to 6-digit; pass 6-digit through. */
const expandHex = (hex: string): string => {
  const h = hex.replace("#", "");
  return h.length === 3 ? `#${h[0]}${h[0]}${h[1]}${h[1]}${h[2]}${h[2]}` : `#${h}`;
};

/** Hex colour + 0..1 alpha → rgba() string. */
export const withAlpha = (hex: string, alpha: number): string => {
  const h = expandHex(hex).slice(1);
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
};

/** Linear mix of two hex colours; t=0 → a, t=1 → b. Returns 6-digit hex. */
export const mixHex = (a: string, b: string, t: number): string => {
  const ha = expandHex(a).slice(1);
  const hb = expandHex(b).slice(1);
  const channel = (offset: number) => {
    const ca = parseInt(ha.slice(offset, offset + 2), 16);
    const cb = parseInt(hb.slice(offset, offset + 2), 16);
    return Math.round(ca + (cb - ca) * Math.min(1, Math.max(0, t)))
      .toString(16)
      .padStart(2, "0");
  };
  return `#${channel(0)}${channel(2)}${channel(4)}`;
};

const dedupeAgainst = (colors: string[], taken: string[]): string[] => {
  const lower = taken.map((c) => c.toLowerCase());
  return colors.filter((c) => !lower.includes(c.toLowerCase()));
};

/**
 * Resolve a named palette to ≥6 ordered mark colours for this storyboard's brand
 * + theme. Unknown/omitted names resolve to "brand", so the palette field is
 * always safe to read straight off the props.
 */
export const paletteFor = (
  name: PaletteName | string | undefined,
  brand: BrandColors,
  theme?: Theme,
): string[] => {
  const { accentColor, secondaryColor } = brand;
  switch (name) {
    case "vivid":
      return VIVID;
    case "pastel":
      return PASTEL;
    case "heat":
      return HEAT;
    case "ocean":
      return OCEAN;
    case "duotone":
      // Only the brand's own two colours, alternating through alpha steps —
      // maximum brand lock-in for identity-heavy storyboards.
      return [
        accentColor,
        secondaryColor,
        withAlpha(accentColor, 0.65),
        withAlpha(secondaryColor, 0.65),
        withAlpha(accentColor, 0.35),
        withAlpha(secondaryColor, 0.35),
      ];
    case "mono": {
      // Theme-text-colour alpha ladder — minimalist/monochrome briefs.
      const ink = theme === "light" ? "#111827" : "#ffffff";
      return [1, 0.8, 0.62, 0.46, 0.32, 0.2].map((a) => withAlpha(ink, a));
    }
    case "brand":
    default:
      return [accentColor, secondaryColor, ...dedupeAgainst(BRAND_FALLBACK, [accentColor, secondaryColor])];
  }
};
