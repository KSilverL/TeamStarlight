import { describe, expect, it } from "vitest";
import { countUp, fadeIn, filmGrade, kenBurns, progress, riseSoft, stagger } from "../animations";

const scaleOf = (transform: string): number => Number(/scale\(([-\d.]+)\)/.exec(transform)![1]);

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

describe("kenBurns", () => {
  it("starts at `from` and ends at `to`", () => {
    expect(kenBurns(0, 90, { from: 1, to: 1.12 })).toBe("scale(1) translate(0%, 0%)");
    expect(scaleOf(kenBurns(90, 90, { from: 1, to: 1.12 }))).toBeCloseTo(1.12);
  });

  it("clamps past the duration", () => {
    expect(kenBurns(999, 90)).toBe(kenBurns(90, 90));
  });

  it("is monotone in scale across the ramp", () => {
    let prev = -Infinity;
    for (let f = 0; f <= 90; f++) {
      const s = scaleOf(kenBurns(f, 90));
      expect(s).toBeGreaterThanOrEqual(prev);
      prev = s;
    }
  });

  it("applies pan as a percentage of the element", () => {
    expect(kenBurns(60, 60, { from: 1, to: 1, panX: 10, panY: -4 })).toBe(
      "scale(1) translate(10%, -4%)",
    );
  });

  it("does not throw on a zero-length slide", () => {
    // interpolate() throws on a non-increasing range — a fixture with
    // durationFrames: 0 would otherwise hard-fail the whole render.
    expect(() => kenBurns(0, 0)).not.toThrow();
  });
});

describe("filmGrade", () => {
  const NEUTRAL = "saturate(1) contrast(1) brightness(1)";

  it("starts at the given grade and resolves to neutral", () => {
    const opts = { frames: 20, saturate: 0.25, contrast: 1.25, brightness: 0.6 };
    expect(filmGrade(0, opts)).toBe("saturate(0.25) contrast(1.25) brightness(0.6)");
    expect(filmGrade(20, opts)).toBe(NEUTRAL);
  });

  it("clamps before the delay and past the end", () => {
    const opts = { delay: 10, frames: 10, saturate: 2 };
    expect(filmGrade(0, opts)).toBe(filmGrade(10, opts));
    expect(filmGrade(999, opts)).toBe(NEUTRAL);
  });

  it("is a neutral no-op with no options", () => {
    // Every channel already at 1 must stay exactly 1 at every frame, so a caller can
    // pass a grade for one channel without accidentally animating the others.
    expect(filmGrade(0)).toBe(NEUTRAL);
    expect(filmGrade(7)).toBe(NEUTRAL);
  });

  it("moves monotonically toward neutral", () => {
    let prev = 0;
    for (let f = 0; f <= 30; f += 5) {
      const sat = Number(/saturate\(([-\d.]+)\)/.exec(filmGrade(f, { frames: 30, saturate: 0 }))![1]);
      expect(sat).toBeGreaterThanOrEqual(prev);
      prev = sat;
    }
  });
});
