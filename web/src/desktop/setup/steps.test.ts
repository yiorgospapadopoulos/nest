import { describe, expect, it } from "vitest";
import type { ModelOption, SetupCheck } from "../../api/types.ts";
import { initialState, type State } from "../../store/state.ts";
import { engineAccount } from "../../test/accounts.ts";
import { modelList, models } from "../../test/fixtures.ts";
import {
  canContinue,
  canFinish,
  canSkip,
  cheapestModel,
  firstChatModel,
  markOf,
  reachable,
  STEPS,
  tailscaleStage,
} from "./steps.ts";

const option = (value: string, display_name = value) =>
  ({ ...models()[0], value, display_name }) as ModelOption;

describe("the engine step", () => {
  it("cannot be skipped or passed without an engine", () => {
    expect(STEPS.filter((step) => step.id !== "first_chat" && !canSkip(step.id))).toEqual([
      expect.objectContaining({ id: "engine" }),
    ]);
    expect(canContinue("engine", false)).toBe(false);
    expect(canContinue("engine", true)).toBe(true);
    expect(canContinue("github", false)).toBe(true);
  });

  it("keeps a first run in the guide, but never one reopened from Settings", () => {
    expect(canFinish(true, false)).toBe(false);
    expect(canFinish(true, true)).toBe(true);
    expect(canFinish(false, false)).toBe(true);
  });
});

describe("a step's mark", () => {
  it("is done before open, open before skipped", () => {
    expect(markOf("ok", true, true, false)).toBe("ok");
    expect(markOf("missing", true, true, false)).toBe("now");
    expect(markOf("missing", false, true, false)).toBe("skipped");
    expect(markOf("not_applicable", false, false, false)).toBe("todo");
    expect(markOf("not_applicable", false, false, true)).toBe("ok");
  });
});

describe("the first chat's model", () => {
  it("picks the cheapest name first, whatever the list's order", () => {
    expect(cheapestModel([option("gpt-5-mini"), option("opus"), option("haiku")])).toBe("haiku");
    expect(cheapestModel([option("opus")])).toBeNull();
  });

  it("uses the first engine signed in", () => {
    const state: State = {
      ...initialState,
      settings: {
        ...initialState.settings,
        accounts: [
          engineAccount({ signed_in: false }),
          engineAccount({ id: "codex", provider: "codex" }),
        ],
      },
      modelLists: { codex: modelList({ models: [option("gpt-5"), option("gpt-5-mini")] }) },
    };
    expect(firstChatModel(state)).toEqual({ provider: "codex", model: "gpt-5-mini" });
  });
});

describe("Tailscale's stage", () => {
  const check = (stage: string | null): SetupCheck => ({
    id: "tailscale",
    title: "Tailscale and iPhone",
    state: "missing",
    message: "",
    detail: null,
    fix: null,
    importance: "optional",
    stage,
    rank: 3,
  });

  it("counts Nest as reachable, for the pairing code, only once it is shared", () => {
    // Regression: the code showed with Tailscale not even installed.
    for (const stage of ["install", "connect", "share", null, "later"]) {
      expect(reachable(tailscaleStage(check(stage)))).toBe(false);
    }
    expect(reachable(tailscaleStage(undefined))).toBe(false);
    expect(reachable(tailscaleStage(check("pair")))).toBe(true);
    expect(reachable(tailscaleStage(check("done")))).toBe(true);
  });
});
