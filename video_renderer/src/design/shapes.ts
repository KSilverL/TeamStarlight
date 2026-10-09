// Shape library: border-radius / clip-path recipes for image masks and decorative
// panels. HookSlide's original circle/blob/hex map moved here verbatim (KEEP IN
// SYNC WITH LLM_service/core/video_schema.py HookSlideSpec.shape for those three);
// the rest are renderer-side treatments available to variants and generated scenes.

/** border-radius values — apply to a square (aspect-ratio 1/1) element. */
export const SHAPE_RADIUS = {
  circle: "50%",
  blob: "62% 38% 55% 45% / 45% 60% 40% 55%",
  blob2: "40% 60% 55% 45% / 55% 40% 60% 45%",
  hex: "10%",
  squircle: "28%",
  /** Arched window: flat bottom, fully rounded top. */
  arch: "50% 50% 6% 6% / 55% 55% 6% 6%",
  pill: "999px",
} as const;

export type ShapeName = keyof typeof SHAPE_RADIUS;

/** clip-path values — for cuts border-radius can't express. */
export const SHAPE_CLIP = {
  /** Diagonal split: keeps the lower-left triangle-ish panel. */
  diagonalCut: "polygon(0 0, 100% 12%, 100% 100%, 0 100%)",
  /** The complementary upper panel. */
  diagonalCutTop: "polygon(0 0, 100% 0, 100% 12%, 0 24%)",
  /** Chevron/arrow pointing right — process steps. */
  chevron: "polygon(0 0, 88% 0, 100% 50%, 88% 100%, 0 100%, 8% 50%)",
  /**
   * Angled BOTTOM edge, sloping down to the left. The media/type seam on
   * ColdOpenSlide's `horizon` variant. Complement of diagonalCut (which slopes the
   * TOP edge), and deliberately the same 12% slope so the two read as one system.
   */
  horizonCut: "polygon(0 0, 100% 0, 100% 88%, 0 100%)",
} as const;

export type ClipName = keyof typeof SHAPE_CLIP;
