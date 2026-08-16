// Word-level text helpers for <WordReveal> (components.tsx): splitting a line into
// independently-animatable words, matching the LLM's emphasis picks against them,
// and giving each word a small deterministic offset so a staggered entrance reads
// as hand-choreographed rather than as a metronome.
//
// Pure and React-free so vitest can cover it — see the note at the top of mosaic.ts.

import { hashUnit } from "./mosaic";

/**
 * Split a line into words, collapsing any run of whitespace. The component
 * re-inserts a single plain space *between* the word spans (never inside them), so
 * the browser still has real line-break opportunities.
 */
export const splitWords = (text: string): string[] =>
  text.trim().split(/\s+/).filter((w) => w.length > 0);

// Leading/trailing punctuation to ignore when matching emphasis. Kept as an
// explicit character class rather than a \p{P} unicode-property escape: the class
// is obvious at a glance and can't behave differently across engines.
const LEADING_PUNCT = /^["'“”‘’(\[{«¿¡\-–—]+/;
const TRAILING_PUNCT = /["'“”‘’)\]}»,.!?:;\-–—]+$/;

/**
 * Comparison form of a word: lowercased and stripped of surrounding punctuation, so
 * an emphasis pick of `faster` still matches the rendered `faster,` and `"Ship"`.
 */
export const normalizeWord = (word: string): string =>
  word.replace(LEADING_PUNCT, "").replace(TRAILING_PUNCT, "").toLowerCase();

/**
 * Which of `words` the storyboard asked to emphasise.
 *
 * The schema carries the literal words rather than indices on purpose: an LLM
 * miscounting an index silently highlights the wrong word with nothing to validate
 * against, whereas a word that doesn't appear in the line is simply ignored here —
 * a no-op, not a wrong render.
 */
export const emphasisFlags = (words: string[], emphasis?: string[]): boolean[] => {
  if (!emphasis || emphasis.length === 0) return words.map(() => false);
  const wanted = new Set(emphasis.map(normalizeWord).filter((w) => w.length > 0));
  return words.map((w) => wanted.has(normalizeWord(w)));
};

export interface WordOffset {
  /** Extra px added to the word's rise distance. */
  dy: number;
  /** Horizontal px the word drifts in from. */
  dx: number;
}

/**
 * A small fixed jitter for the i-th word, so words don't all travel exactly the
 * same distance. Hash-derived rather than a magic-number table: it stays
 * deterministic (same word index → same offset on every render) and needs no
 * maintenance as lines get longer.
 */
export const wordOffset = (index: number, spread: number = 1): WordOffset => ({
  dy: (hashUnit(index, 0, 0, 17) * 2 - 1) * 8 * spread,
  dx: (hashUnit(index, 1, 0, 17) * 2 - 1) * 4 * spread,
});
