// The pickers of a pixie's details (PixieDetails.swift's PixieSettings, PixieModelPicker):
// Model with a section per engine, so choosing a model chooses its engine (B91), and
// Thinking and Permissions following that engine's models, with no Default entries (B94).
import type { Effort, PermissionMode, Pixie, UpdatePixieBody } from "../../api/types.ts";
import { effortLabel, PERMISSIONS } from "../../screens/chat/options.ts";
import { isSelected, supportsAuto, thinkingLevels } from "../../store/catalog.ts";
import { catalogFor, modelSections, modelTitle, pixieCanRunOn } from "../../store/selectors.ts";
import type { State } from "../../store/state.ts";
import type { MenuEntry } from "../ui/menuItems.ts";
import { AUTONOMY, PROJECT_ACCESS } from "./words.ts";

// The Mac's words for the permission modes, where they differ from the phone's.
const PERMISSION_SUMMARY: Partial<Record<PermissionMode, string>> = {
  auto: "Asks only when Claude Code judges an action risky",
};

type Save = (body: UpdatePixieBody) => void;

export interface PixieRow {
  title: string;
  value: string;
  enabled: boolean;
  items: () => MenuEntry[];
}

/** Model, Thinking, Permissions, Project files and Autonomy, each a value opening its choices. */
export function settingsRows(state: State, pixie: Pixie, save: Save): PixieRow[] {
  const catalog = catalogFor(state, pixie.provider);
  // The model its runs ask for: its own, or its engine's default (B94).
  const runs = pixie.model ?? catalog.defaultModel;
  const levels = thinkingLevels(catalog, runs);
  const auto = supportsAuto(catalog, runs);
  const permission = PERMISSIONS.find((o) => o.value === pixie.permission_mode);
  return [
    {
      title: "Model",
      value: modelTitle(state, pixie.model, pixie.provider),
      enabled: true,
      items: () => modelItems(state, pixie, save),
    },
    {
      title: "Thinking",
      value:
        levels.length === 0
          ? "Not available"
          : pixie.effort === null
            ? "-"
            : effortLabel(pixie.effort),
      enabled: levels.length > 0,
      items: () => [
        { type: "section", title: "Thinking" },
        ...levels.map((level: Effort) => ({
          title: effortLabel(level),
          checked: pixie.effort === level,
          onSelect: () => {
            save({ effort: level });
          },
        })),
      ],
    },
    {
      title: "Permissions",
      value: permission?.label ?? pixie.permission_mode,
      enabled: true,
      // Auto only where the model offers it, as in any chat.
      items: () => [
        { type: "section", title: "Permission mode" },
        ...PERMISSIONS.filter((o) => auto || o.value !== "auto").map((option) => ({
          title: option.label,
          detail: PERMISSION_SUMMARY[option.value] ?? option.hint ?? "",
          checked: pixie.permission_mode === option.value,
          onSelect: () => {
            save({ permission_mode: option.value });
          },
        })),
      ],
    },
    {
      title: "Project files",
      value: PROJECT_ACCESS.find((c) => c.value === pixie.project_access)?.label ?? "Unknown",
      enabled: true,
      items: () => [
        { type: "section", title: "Project files" },
        ...PROJECT_ACCESS.map((choice) => ({
          title: choice.label,
          detail: choice.summary,
          checked: pixie.project_access === choice.value,
          onSelect: () => {
            save({ project_access: choice.value });
          },
        })),
      ],
    },
    {
      title: "Autonomy",
      value: AUTONOMY.find((c) => c.value === pixie.autonomy)?.label ?? "Unknown",
      enabled: true,
      items: () => [
        { type: "section", title: "Autonomy" },
        ...AUTONOMY.map((choice) => ({
          title: choice.label,
          detail: choice.summary,
          checked: pixie.autonomy === choice.value,
          onSelect: () => {
            save({ autonomy: choice.value });
          },
        })),
      ],
    },
  ];
}

/**
 * Each engine's section with its plan or that it is not signed in, then its real models;
 * a list not loaded says models are unavailable. Another engine's model names it too.
 */
export function modelItems(state: State, pixie: Pixie, save: Save): MenuEntry[] {
  return modelSections(state, pixie.provider, true).flatMap((section): MenuEntry[] => {
    const mine = section.provider === pixie.provider;
    const choosable = pixieCanRunOn(state, section.provider);
    const head: MenuEntry[] = [{ type: "section", title: section.title }];
    if (section.detail !== "") head.push({ type: "note", text: section.detail });
    if (section.catalog.models.length === 0) {
      head.push({ title: "Models unavailable", disabled: true, onSelect: () => undefined });
    }
    return [
      ...head,
      ...section.catalog.models.map((option) => ({
        title: option.display_name,
        detail: option.description,
        warns: section.weak?.includes(option.value) === true,
        checked: mine && isSelected(section.catalog, option, pixie.model),
        // A stopped server's local models show, not choosable (B116).
        disabled: !choosable || section.unavailable?.includes(option.value) === true,
        onSelect: () => {
          save(
            mine ? { model: option.value } : { provider: section.provider, model: option.value },
          );
        },
      })),
    ];
  });
}
