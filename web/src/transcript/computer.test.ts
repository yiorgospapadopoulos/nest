import { describe, expect, it } from "vitest";

import { namedAction } from "./computer.ts";

describe("namedAction", () => {
  it("takes an act's first line once its element has a name", () => {
    expect(namedAction('Pressed "Send" in Mail.\nWindow w1: Inbox')).toEqual({
      name: "Pressed",
      arg: '"Send" in Mail',
    });
  });

  it("keeps the row as it is for an element without a name", () => {
    expect(namedAction("Pressed e4 in Mail.")).toBeNull();
  });
});
