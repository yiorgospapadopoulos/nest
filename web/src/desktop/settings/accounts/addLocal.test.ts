import { describe, expect, it } from "vitest";
import { foundModel } from "../../../test/accounts.ts";
import { isChosen, picked, withFound } from "./addLocal.ts";

// Ported from NestKit's LocalModelsStoreTests (AddLocalFlow).
describe("Add local model choices", () => {
  const good = foundModel({ model: "q30", tools: "good" });
  const weak = foundModel({ model: "q4", tools: "weak" });
  const unknown = foundModel({ model: "llama", tools: "unknown" });
  const added = foundModel({ model: "old", tools: "good", added: true });
  const big = foundModel({
    model: "big",
    tools: "good",
    memory_warning: "Needs about 40 GB of this computer's 24 GB.",
  });

  it("chooses the models good at tools on Find, never one too big for the memory", () => {
    const chosen = withFound(new Set(), [good, weak, unknown, added, big], "find");
    expect([good, weak, unknown, big].map((m) => isChosen(chosen, m))).toEqual([
      true,
      false,
      false,
      false,
    ]);
    expect(isChosen(chosen, added)).toBe(true);
    expect(picked(chosen, [good, weak, added]).map((m) => m.model)).toEqual(["q30"]);
  });

  it("chooses any not weak at tools on an address, still not one too big", () => {
    const chosen = withFound(new Set(), [unknown, weak, big], "address");
    expect(picked(chosen, [unknown, weak, big]).map((m) => m.model)).toEqual(["llama"]);
  });
});
