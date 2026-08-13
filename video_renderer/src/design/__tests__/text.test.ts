import { describe, expect, it } from "vitest";
import { emphasisFlags, normalizeWord, splitWords, wordOffset } from "../text";

describe("splitWords", () => {
  it("splits on whitespace and collapses runs", () => {
    expect(splitWords("Build AI agents on AWS")).toEqual(["Build", "AI", "agents", "on", "AWS"]);
    expect(splitWords("  ship   faster\n than  ever ")).toEqual(["ship", "faster", "than", "ever"]);
  });

  it("returns an empty list for blank input", () => {
    expect(splitWords("")).toEqual([]);
    expect(splitWords("   \n ")).toEqual([]);
  });
});

describe("normalizeWord", () => {
  it("lowercases and strips surrounding punctuation", () => {
    expect(normalizeWord("Faster,")).toBe("faster");
    expect(normalizeWord('"Ship"')).toBe("ship");
    expect(normalizeWord("(really)")).toBe("really");
    expect(normalizeWord("API?")).toBe("api");
  });

  it("keeps word-internal punctuation", () => {
    expect(normalizeWord("start-up")).toBe("start-up");
    expect(normalizeWord("don't")).toBe("don't");
  });
});

describe("emphasisFlags", () => {
  const words = ["Ship", "faster,", "than", "the", "market"];

  it("flags nothing when no emphasis is given", () => {
    expect(emphasisFlags(words)).toEqual([false, false, false, false, false]);
    expect(emphasisFlags(words, [])).toEqual([false, false, false, false, false]);
  });

  it("matches through punctuation and case", () => {
    expect(emphasisFlags(words, ["faster"])).toEqual([false, true, false, false, false]);
    expect(emphasisFlags(words, ["SHIP"])).toEqual([true, false, false, false, false]);
  });

  it("ignores an emphasis word that isn't in the line", () => {
    // A no-op, not a wrong render — the reason the schema carries words, not indices.
    expect(emphasisFlags(words, ["slower"])).toEqual([false, false, false, false, false]);
  });

  it("flags every occurrence of a repeated word", () => {
    expect(emphasisFlags(["more", "and", "more"], ["more"])).toEqual([true, false, true]);
  });
});

describe("wordOffset", () => {
  it("is deterministic per index", () => {
    expect(wordOffset(3)).toEqual(wordOffset(3));
  });

  it("varies between adjacent words", () => {
    expect(wordOffset(0).dy).not.toBe(wordOffset(1).dy);
  });

  it("stays small enough not to break the line's shape", () => {
    for (let i = 0; i < 40; i++) {
      const { dx, dy } = wordOffset(i);
      expect(Math.abs(dy)).toBeLessThanOrEqual(8);
      expect(Math.abs(dx)).toBeLessThanOrEqual(4);
    }
  });

  it("scales with spread", () => {
    expect(Math.abs(wordOffset(5, 2).dy)).toBeCloseTo(Math.abs(wordOffset(5, 1).dy) * 2, 10);
  });

  it("never pushes riseSoft's distance negative", () => {
    // WordReveal passes `distance: 26 + dy`; a dy below -26 would invert the rise.
    for (let i = 0; i < 100; i++) expect(26 + wordOffset(i).dy).toBeGreaterThan(0);
  });
});
