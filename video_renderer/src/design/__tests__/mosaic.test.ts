import { describe, expect, it } from "vitest";
import {
  cellAlpha,
  hashUnit,
  isDrawableGrid,
  mosaicGrid,
  mosaicRamp,
  mosaicShade,
  rampColor,
  valueNoise3,
} from "../mosaic";

const HEX = /^#[0-9a-f]{6}$/i;

describe("hashUnit", () => {
  it("stays in [0,1)", () => {
    for (let x = -20; x <= 20; x++) {
      for (let y = -20; y <= 20; y++) {
        const v = hashUnit(x, y);
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThan(1);
      }
    }
  });

  it("is deterministic across calls", () => {
    expect(hashUnit(3, 7, 2, 9)).toBe(hashUnit(3, 7, 2, 9));
  });

  it("is asymmetric in x/y", () => {
    // A symmetric hash would give every (col,row) pair on an anti-diagonal the same
    // threshold, turning the dissolve into diagonal stripes instead of a scatter.
    expect(hashUnit(0, 1)).not.toBe(hashUnit(1, 0));
    expect(hashUnit(2, 5)).not.toBe(hashUnit(5, 2));
  });

  it("separates seeds and z", () => {
    expect(hashUnit(4, 4, 0, 0)).not.toBe(hashUnit(4, 4, 0, 1));
    expect(hashUnit(4, 4, 0, 0)).not.toBe(hashUnit(4, 4, 1, 0));
  });

  it("spreads roughly uniformly", () => {
    const buckets = new Array(4).fill(0);
    for (let x = 0; x < 40; x++) {
      for (let y = 0; y < 40; y++) buckets[Math.floor(hashUnit(x, y) * 4)]++;
    }
    // 1600 samples over 4 buckets — a badly clustered hash fails this by miles.
    for (const count of buckets) expect(count).toBeGreaterThan(250);
  });
});

describe("valueNoise3", () => {
  it("stays in [0,1]", () => {
    for (let i = 0; i < 200; i++) {
      const v = valueNoise3(i * 0.37, i * 0.11, i * 0.05);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });

  it("equals the lattice value exactly at integer coordinates", () => {
    expect(valueNoise3(3, 5, 2)).toBeCloseTo(hashUnit(3, 5, 2), 10);
  });

  it("is continuous — no lattice seams", () => {
    let prev = valueNoise3(0, 0.5, 0.25);
    for (let x = 0.01; x <= 4; x += 0.01) {
      const v = valueNoise3(x, 0.5, 0.25);
      expect(Math.abs(v - prev)).toBeLessThan(0.05);
      prev = v;
    }
  });
});

describe("mosaicGrid", () => {
  it("derives a square cell from the short edge, at every aspect ratio", () => {
    expect(mosaicGrid(1080, 1920)).toEqual({ cell: 180, cols: 6, rows: 11 });
    expect(mosaicGrid(1920, 1080)).toEqual({ cell: 180, cols: 11, rows: 6 });
    expect(mosaicGrid(1080, 1080)).toEqual({ cell: 180, cols: 6, rows: 6 });
  });

  it("always covers the frame", () => {
    for (const [w, h] of [[1080, 1920], [1920, 1080], [1080, 1080], [720, 1280]]) {
      const g = mosaicGrid(w, h);
      expect(g.cols * g.cell).toBeGreaterThanOrEqual(w);
      expect(g.rows * g.cell).toBeGreaterThanOrEqual(h);
    }
  });

  it("clamps an absurd cell count instead of producing a 1px grid", () => {
    expect(mosaicGrid(1080, 1920, 0).cell).toBe(540);
    expect(mosaicGrid(1080, 1920, -5).cell).toBe(540);
  });

  it("flags grids too large to draw as DOM nodes", () => {
    expect(isDrawableGrid(mosaicGrid(1080, 1920))).toBe(true);
    expect(isDrawableGrid(mosaicGrid(1080, 1920, 40))).toBe(false);
  });
});

describe("mosaicShade", () => {
  it("stays in [0,1] across a whole slide", () => {
    for (let frame = 0; frame < 200; frame += 3) {
      for (let col = 0; col < 6; col++) {
        for (let row = 0; row < 11; row++) {
          const v = mosaicShade(col, row, frame);
          expect(v).toBeGreaterThanOrEqual(0);
          expect(v).toBeLessThanOrEqual(1);
        }
      }
    }
  });

  it("moves slowly — a cell barely changes frame to frame", () => {
    // The whole point of the default speedFrames: undulation you feel, not flicker.
    for (let frame = 0; frame < 120; frame++) {
      const delta = Math.abs(mosaicShade(2, 3, frame + 1) - mosaicShade(2, 3, frame));
      expect(delta).toBeLessThan(0.03);
    }
  });

  it("actually moves over a slide's length", () => {
    expect(Math.abs(mosaicShade(2, 3, 120) - mosaicShade(2, 3, 0))).toBeGreaterThan(0.005);
  });
});

describe("mosaicRamp", () => {
  const PRIMARY = "#f6f7fb";
  const SECONDARY = "#4f46e5";
  const ACCENT = "#7c3aed";

  it("returns six valid hex stops", () => {
    const ramp = mosaicRamp(PRIMARY, SECONDARY, ACCENT);
    expect(ramp).toHaveLength(6);
    for (const stop of ramp) expect(stop).toMatch(HEX);
  });

  it("terminates in primaryColor — this is what makes it theme-correct", () => {
    expect(mosaicRamp(PRIMARY, SECONDARY, ACCENT).at(-1)).toBe(PRIMARY);
    expect(mosaicRamp("#0d1117", SECONDARY, ACCENT).at(-1)).toBe("#0d1117");
  });

  it("collapses to a flat primaryColor field at contrast 0", () => {
    for (const stop of mosaicRamp(PRIMARY, SECONDARY, ACCENT, 0)) expect(stop).toBe(PRIMARY);
  });

  it("lifts the darkest stop toward primary as contrast drops", () => {
    const full = mosaicRamp(PRIMARY, SECONDARY, ACCENT, 1)[0];
    const lifted = mosaicRamp(PRIMARY, SECONDARY, ACCENT, 0.85)[0];
    expect(lifted).not.toBe(full);
    const lum = (hex: string) =>
      parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16);
    // primaryColor here is near-white, so pulling toward it must brighten.
    expect(lum(lifted)).toBeGreaterThan(lum(full));
  });
});

describe("rampColor", () => {
  const ramp = mosaicRamp("#f6f7fb", "#4f46e5", "#7c3aed");

  it("hits the endpoints", () => {
    expect(rampColor(0, ramp)).toBe(ramp[0]);
    expect(rampColor(1, ramp)).toBe(ramp[5]);
  });

  it("clamps outside [0,1]", () => {
    expect(rampColor(-2, ramp)).toBe(ramp[0]);
    expect(rampColor(9, ramp)).toBe(ramp[5]);
  });

  it("lands on the interior stops", () => {
    expect(rampColor(0.2, ramp)).toBe(ramp[1]);
    expect(rampColor(0.6, ramp)).toBe(ramp[3]);
  });

  it("survives degenerate ramps", () => {
    expect(rampColor(0.5, ["#123456"])).toBe("#123456");
    expect(rampColor(0.5, [])).toMatch(HEX);
  });
});

describe("cellAlpha", () => {
  const thresholds = [0, 0.13, 0.37, 0.5, 0.78, 1];

  it("is fully painted at dissolve 0 and fully gone at dissolve 1", () => {
    for (const t of thresholds) {
      expect(cellAlpha(t, 0)).toBe(1);
      expect(cellAlpha(t, 1)).toBe(0);
    }
  });

  it("is monotonically non-increasing in dissolve", () => {
    for (const t of thresholds) {
      let prev = 2;
      for (let d = 0; d <= 1.0001; d += 0.02) {
        const v = cellAlpha(t, d);
        expect(v).toBeLessThanOrEqual(prev + 1e-9);
        prev = v;
      }
    }
  });

  it("drops low-threshold cells strictly before high-threshold ones", () => {
    // This ordering is the scatter: without it every cell would fade together and
    // the dissolve would just be a crossfade.
    const early = cellAlpha(0.1, 0.35);
    const late = cellAlpha(0.9, 0.35);
    expect(early).toBeLessThan(late);
    expect(early).toBe(0);
    expect(late).toBe(1);
  });

  it("feathers rather than popping", () => {
    const mid = cellAlpha(0.5, 0.5);
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(1);
  });

  it("does not divide by zero on a zero feather", () => {
    expect(cellAlpha(0.5, 0.9, 0)).toBe(0);
    expect(Number.isNaN(cellAlpha(0.5, 0.1, 0))).toBe(false);
  });
});
