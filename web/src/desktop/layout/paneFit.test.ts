// Ported from NestKitTests/PaneFitTests.swift: a narrow pane gives way in order, and a
// selector takes a short whole-word label rather than a cut one ("H." for Haiku).
import { describe, expect, it } from "vitest";
import { shortChoiceLabel } from "../../screens/chat/options.ts";
import { paneFit } from "./paneFit.ts";

describe("a pane's fit", () => {
  it("shows everything in a wide pane", () => {
    expect(paneFit(828)).toEqual({
      showsPullRequest: true,
      showsPlaceName: true,
      showsContext: true,
      compact: false,
    });
  });

  it("gives way in order: the place's name, the pull request, the context, full labels", () => {
    expect(paneFit(560).showsPlaceName).toBe(true);
    expect(paneFit(559).showsPlaceName).toBe(false);
    expect(paneFit(420).showsPullRequest).toBe(true);
    expect(paneFit(419).showsPullRequest).toBe(false);
    expect(paneFit(380).compact).toBe(false);
    expect(paneFit(379).compact).toBe(true);
    expect(paneFit(360).showsContext).toBe(true);
    expect(paneFit(359).showsContext).toBe(false);
  });

  it("shortens selector labels to whole words", () => {
    expect(shortChoiceLabel("model", "Haiku 4.5")).toBe("Haiku");
    expect(shortChoiceLabel("model", "Opus")).toBe("Opus");
    expect(shortChoiceLabel("effort", "Medium")).toBe("Med");
    expect(shortChoiceLabel("effort", "Extra high")).toBe("X-high");
    expect(shortChoiceLabel("effort", "High")).toBe("High");
    expect(shortChoiceLabel("permission", "Accept edits")).toBe("Edits");
    expect(shortChoiceLabel("permission", "Ask")).toBe("Ask");
  });
});
