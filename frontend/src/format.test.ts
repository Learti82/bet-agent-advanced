import { describe, expect, it } from "vitest";
import { addDays, combinedOdds, hr, smallPct } from "./format";

describe("combinedOdds", () => {
  it("multiplies decimal odds", () => {
    expect(combinedOdds([1.5, 2.0, 1.25])).toBeCloseTo(3.75, 10);
  });
  it("returns null for an empty ticket or a missing/invalid price", () => {
    expect(combinedOdds([])).toBeNull();
    expect(combinedOdds([1.5, null])).toBeNull();
    expect(combinedOdds([1.5, 1.0])).toBeNull();
  });
  it("reaches 110 only with enough legs", () => {
    expect(combinedOdds(Array(11).fill(1.53))!).toBeGreaterThan(100);
  });
});

describe("formatting", () => {
  it("formats hit rates and small probabilities without fake precision", () => {
    expect(hr({ k: 7, n: 10 })).toBe("7/10");
    expect(hr({ k: 0, n: 0 })).toBe("no data");
    expect(smallPct(0.0123)).toBe("1.2%");
    expect(smallPct(0.456)).toBe("46%");
  });
  it("adds days across month boundaries", () => {
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
  });
});
