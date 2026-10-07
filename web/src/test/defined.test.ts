import { describe, expect, it } from "vitest";
import { defined } from "./defined.ts";

describe("defined", () => {
  it("passes values through and fails on missing ones", () => {
    expect(defined(0)).toBe(0);
    expect(() => {
      defined<number>(null);
    }).toThrow("expected a value");
    expect(() => {
      defined<number>(undefined);
    }).toThrow("expected a value");
  });
});
