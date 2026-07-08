import { describe, expect, it } from "vitest";
import { PALETTE_NAMES, mixHex, paletteFor, withAlpha } from "../palettes";

const HEX_OR_RGBA = /^(#[0-9a-fA-F]{6}|rgba\(\d+,\d+,\d+,[\d.]+\))$/;
const brand = { accentColor: "#f5c84c", secondaryColor: "#2d4ed8" };

describe("paletteFor", () => {
  it("resolves every named palette to at least 6 valid colours in both themes", () => {
    for (const name of PALETTE_NAMES) {
      for (const theme of ["dark", "light"] as const) {
        const colors = paletteFor(name, brand, theme);
        expect(colors.length, `${name}/${theme} length`).toBeGreaterThanOrEqual(6);
        for (const c of colors) {
          expect(c, `${name}/${theme} colour ${c}`).toMatch(HEX_OR_RGBA);
        }
      }
    }
  });

  it("defaults unknown/undefined names to the brand palette (accent + secondary first)", () => {
    const fallback = paletteFor(undefined, brand);
    const unknown = paletteFor("not-a-palette", brand);
    expect(fallback[0]).toBe("#f5c84c");
    expect(fallback[1]).toBe("#2d4ed8");
    expect(unknown).toEqual(fallback);
  });

  it("brand palette filters brand duplicates out of the fallback ladder", () => {
    // accent (#f5c84c) is also the first fallback colour — it must not appear twice.
    const colors = paletteFor("brand", brand);
    const occurrences = colors.filter((c) => c.toLowerCase() === "#f5c84c").length;
    expect(occurrences).toBe(1);
  });

  it("duotone uses only the two brand hues", () => {
    const colors = paletteFor("duotone", brand);
    // Every colour derives from accent or secondary (solid or alpha step).
    expect(colors[0]).toBe("#f5c84c");
    expect(colors[1]).toBe("#2d4ed8");
    expect(colors[2]).toBe(withAlpha("#f5c84c", 0.65));
  });
});

describe("mixHex", () => {
  it("returns the endpoints at t=0 and t=1", () => {
    expect(mixHex("#000000", "#ffffff", 0)).toBe("#000000");
    expect(mixHex("#000000", "#ffffff", 1)).toBe("#ffffff");
  });

  it("returns the midpoint at t=0.5", () => {
    expect(mixHex("#000000", "#ffffff", 0.5)).toBe("#808080");
  });

  it("expands 3-digit hex inputs", () => {
    expect(mixHex("#000", "#fff", 1)).toBe("#ffffff");
  });
});

describe("withAlpha", () => {
  it("builds an rgba() string from hex + alpha", () => {
    expect(withAlpha("#2d4ed8", 0.5)).toBe("rgba(45,78,216,0.5)");
  });
});
