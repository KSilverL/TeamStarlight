import { describe, expect, it } from "vitest";
import { countUp, fadeIn, progress, riseSoft, stagger } from "../animations";

const FPS = 30;

describe("stagger", () => {
  it("scales the delay by index", () => {
    expect(stagger(0)).toBe(0);
    expect(stagger(3, 6)).toBe(18);
  });
});

describe("fadeIn", () => {
  it("clamps to [0,1] at and beyond the endpoints", () => {
    expect(fadeIn(-5)).toBe(0);
    expect(fadeIn(0)).toBe(0);
    expect(fadeIn(12)).toBe(1);
    expect(fadeIn(999)).toBe(1);
  });

  it("is monotonically non-decreasing across the ramp", () => {
    let prev = -1;
    for (let f = 0; f <= 12; f++) {
      const v = fadeIn(f);
      expect(v).toBeGreaterThanOrEqual(prev);
      prev = v;
    }
  });

  it("honours delay", () => {
    expect(fadeIn(5, { delay: 5 })).toBe(0);
    expect(fadeIn(17, { delay: 5 })).toBe(1);
  });
});

describe("progress", () => {
  it("runs 0→1 clamped between the frames", () => {
    expect(progress(0, { to: 20 })).toBe(0);
    expect(progress(10, { to: 20 })).toBeCloseTo(0.5);
    expect(progress(20, { to: 20 })).toBe(1);
    expect(progress(50, { to: 20 })).toBe(1);
  });
});

describe("countUp", () => {
  it("ramps to the target and holds", () => {
    expect(countUp(0, 100)).toBe(0);
    expect(countUp(15, 100)).toBe(50);
    expect(countUp(30, 100)).toBe(100);
    expect(countUp(200, 100)).toBe(100);
  });

  it("rounds in-flight values", () => {
    expect(Number.isInteger(countUp(7, 100))).toBe(true);
  });
});

describe("riseSoft", () => {
  it("starts hidden and low, ends visible and settled", () => {
    const start = riseSoft(0);
    expect(start.opacity).toBe(0);
    expect(start.transform).toBe("translateY(30px)");

    const end = riseSoft(30);
    expect(end.opacity).toBe(1);
    expect(end.transform).toBe("translateY(0px)");
  });
});
