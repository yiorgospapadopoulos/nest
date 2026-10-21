import { describe, expect, it } from "vitest";
import type { ModelOption } from "../api/types.ts";
import { defined } from "../test/defined.ts";
import { agentDefaults, models } from "../test/fixtures.ts";
import {
  choosingModel,
  effortAfterSwitching,
  fallbackEffort,
  isSelected,
  type ModelCatalog,
  modelInfo,
  modelLabel,
  newChatChoices,
  newChatPermission,
  realModels,
  standardEffort,
  supportsAuto,
  switchingEngine,
  thinkingLevels,
} from "./catalog.ts";

const claude: ModelCatalog = { models: realModels(models()), defaultModel: "opus" };

function gpt(value: string, levels: string[] = ["low", "medium", "high"]): ModelOption {
  return {
    value,
    display_name: value.toUpperCase(),
    description: "",
    effort_levels: levels,
    supports_effort: levels.length > 0,
    supports_auto_mode: false,
    claude_code_effort: null,
  };
}

const codex: ModelCatalog = {
  models: [gpt("gpt-5.5"), gpt("gpt-mini", [])],
  defaultModel: "gpt-5.5",
};

describe("a model catalog (NestKit ModelCatalog, B94)", () => {
  it("offers real models only, never the engine's default entry", () => {
    expect(realModels(models()).map((m) => m.value)).toEqual(["opus", "haiku", "claude-opus-4-6"]);
  });

  it("reads a chat without a model as the engine's default", () => {
    expect(modelInfo(claude, null)?.value).toBe("opus");
    expect(modelInfo(claude, "haiku")?.value).toBe("haiku");
    expect(modelInfo(claude, "gone")).toBeUndefined();
  });

  it("labels a model by its name, else its value, else the default, else Model", () => {
    expect(modelLabel(claude, "haiku")).toBe("Haiku 4.5");
    expect(modelLabel(claude, null)).toBe("Opus 5.5");
    expect(modelLabel(claude, "claude-old")).toBe("claude-old");
    expect(modelLabel({ models: [], defaultModel: "opus" }, null)).toBe("opus");
    expect(modelLabel({ models: [], defaultModel: null }, null)).toBe("Model");
  });

  it("checks the chat's model, or the default for none", () => {
    const opus = defined(claude.models[0]);
    const haiku = defined(claude.models[1]);
    expect(isSelected(claude, opus, null)).toBe(true);
    expect(isSelected(claude, haiku, null)).toBe(false);
    expect(isSelected(claude, haiku, "haiku")).toBe(true);
  });

  it("reads a stored alias or model id as the listed model it stands for", () => {
    // Claude Code's own list names full ids, newest first; chats may hold "opus" (B102).
    const listed: ModelCatalog = {
      models: [
        { ...gpt("claude-opus-5-5"), display_name: "Opus 5.5" },
        { ...gpt("sonnet[1m]"), display_name: "Sonnet 5.5", resolved_model: "claude-sonnet-5-5" },
        { ...gpt("claude-opus-4-8"), display_name: "Opus 4.8" },
      ],
      defaultModel: "claude-opus-5-5",
    };
    const [opus55, sonnet, opus48] = listed.models.map((m) => defined(m));
    expect(modelLabel(listed, "opus")).toBe("Opus 5.5");
    expect(modelLabel(listed, "OPUS")).toBe("Opus 5.5");
    expect(modelLabel(listed, "claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(modelLabel(listed, "sonnet")).toBe("Sonnet 5.5");
    expect(modelLabel(listed, "haiku")).toBe("haiku");
    // Only a bare family name is an alias.
    expect(modelLabel(listed, "claude-opus")).toBe("claude-opus");
    expect(isSelected(listed, defined(opus55), "opus")).toBe(true);
    expect(isSelected(listed, defined(opus48), "opus")).toBe(false);
    expect(isSelected(listed, defined(sonnet), "claude-sonnet-5-5")).toBe(true);
    expect(isSelected(listed, defined(opus48), "claude-old")).toBe(false);
  });

  it("offers a model's own thinking levels in order, every level for an unknown one", () => {
    expect(thinkingLevels(claude, "claude-opus-4-6")).toEqual(["low", "medium", "high", "max"]);
    expect(thinkingLevels(claude, "haiku")).toEqual([]);
    expect(thinkingLevels(claude, "gone")).toEqual(["low", "medium", "high", "xhigh", "max"]);
    // A level the model lists without taking thinking is not offered.
    const odd = { models: [{ ...gpt("x"), supports_effort: false }], defaultModel: null };
    expect(thinkingLevels(odd, "x")).toEqual([]);
  });

  it("picks Medium or the nearest level, the lower of two as near", () => {
    expect(standardEffort(["low", "medium", "high"])).toBe("medium");
    expect(standardEffort(["low", "high"])).toBe("low");
    expect(standardEffort(["high", "max"])).toBe("high");
    expect(standardEffort([])).toBeNull();
  });

  it("keeps the current level as far as the model takes it", () => {
    expect(fallbackEffort("max", ["low", "medium", "high"])).toBe("high");
    expect(fallbackEffort("medium", ["low", "medium"])).toBe("medium");
    expect(fallbackEffort("low", ["high"])).toBeNull();
    expect(fallbackEffort(null, ["high"])).toBeNull();
  });

  it("keeps the thinking after a switch, else Medium or the nearest", () => {
    expect(effortAfterSwitching(claude, "max", "claude-opus-4-6")).toBe("max");
    expect(effortAfterSwitching(codex, "max", "gpt-5.5")).toBe("high");
    expect(effortAfterSwitching(codex, null, "gpt-5.5")).toBe("medium");
    expect(effortAfterSwitching(codex, "high", "gpt-mini")).toBeNull();
  });

  it("knows which models take Auto", () => {
    expect(supportsAuto(claude, "opus")).toBe(true);
    expect(supportsAuto(claude, "haiku")).toBe(false);
    expect(supportsAuto(claude, "gone")).toBe(false);
  });

  it("keeps a new chat's mode unless Auto is not offered", () => {
    expect(newChatPermission(claude, null, "opus", "acceptEdits")).toBe("acceptEdits");
    expect(newChatPermission(claude, "auto", "opus", "default")).toBe("auto");
    expect(newChatPermission(claude, "auto", "haiku", "plan")).toBe("plan");
    expect(newChatPermission(claude, "auto", "haiku", "auto")).toBe("default");
    expect(newChatPermission(claude, null, "haiku", "auto")).toBe("default");
  });
});

describe("a new chat's choices (NestKit NewChatChoices, B94)", () => {
  const defaults = agentDefaults({
    provider: "claude",
    model: "claude-opus-4-6",
    effort: "max",
    permission_mode: "acceptEdits",
  });

  it("start from the concrete agent defaults", () => {
    expect(newChatChoices(defaults, claude)).toEqual({
      provider: "claude",
      model: "claude-opus-4-6",
      effort: "max",
      permission: "acceptEdits",
    });
  });

  it("fill what the defaults leave out from the engine", () => {
    const bare = agentDefaults({
      provider: null,
      model: null,
      effort: null,
      permission_mode: null,
    });
    expect(newChatChoices(bare, claude)).toEqual({
      provider: "claude",
      model: "opus",
      effort: "medium",
      permission: "default",
    });
    expect(newChatChoices({ ...bare, provider: "codex" }, codex)).toMatchObject({
      provider: "codex",
      model: "gpt-5.5",
    });
  });

  it("start another engine on its default model with Medium, keeping the mode", () => {
    const start = newChatChoices(defaults, claude);
    expect(switchingEngine(start, "codex", codex, defaults)).toEqual({
      provider: "codex",
      model: "gpt-5.5",
      effort: "medium",
      permission: "acceptEdits",
    });
    expect(switchingEngine(start, "claude", claude, defaults)).toBe(start);
  });

  it("take the defaults' model and thinking again back on their engine", () => {
    const onCodex = {
      provider: "codex",
      model: "gpt-5.5",
      effort: "low" as const,
      permission: "plan" as const,
    };
    expect(switchingEngine(onCodex, "claude", claude, defaults)).toEqual({
      provider: "claude",
      model: "claude-opus-4-6",
      effort: "max",
      permission: "plan",
    });
    const noModel = agentDefaults({ provider: "claude", model: null, effort: null });
    expect(switchingEngine(onCodex, "claude", claude, noModel)).toMatchObject({
      model: "opus",
      effort: "medium",
    });
  });

  it("choose a model of another engine, the engine following first", () => {
    const start = newChatChoices(defaults, claude);
    expect(choosingModel(start, "gpt-mini", "codex", codex, defaults)).toEqual({
      provider: "codex",
      model: "gpt-mini",
      effort: null,
      permission: "acceptEdits",
    });
    expect(
      choosingModel(start, "haiku", "claude", claude, { ...defaults, permission_mode: "auto" }),
    ).toEqual({
      provider: "claude",
      model: "haiku",
      effort: null,
      permission: "acceptEdits",
    });
  });

  it("drop Auto for a model without it", () => {
    const auto = {
      provider: "claude",
      model: "opus",
      effort: "high" as const,
      permission: "auto" as const,
    };
    expect(choosingModel(auto, "haiku", "claude", claude, defaults).permission).toBe("acceptEdits");
  });
});
