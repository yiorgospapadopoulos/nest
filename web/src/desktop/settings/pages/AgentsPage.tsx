import type { AgentDefaults, SessionMode, StuckSettings } from "../../../api/types.ts";
import {
  CLAUDE,
  effortAfterSwitching,
  modelLabel,
  supportsAuto,
  thinkingLevels,
} from "../../../store/catalog.ts";
import { useStore } from "../../../store/context.ts";
import { catalogFor, modelSections } from "../../../store/selectors.ts";
import { effortLabel, PERMISSIONS } from "../../../screens/chat/options.ts";
import { Segmented } from "../../ui/controls.tsx";
import type { MenuEntry } from "../../ui/menuItems.ts";
import { choiceItems } from "../parts1/choices.ts";
import { Dropdown } from "../rows.tsx";
import { STUCK_THRESHOLDS, stuckChoices, stuckLabel } from "../parts1/words.ts";
import { SettingsRow, SettingsSection } from "../rows.tsx";

const MODES: { value: SessionMode; label: string }[] = [
  { value: "in_place", label: "Current branch" },
  { value: "worktree", label: "New worktree" },
];

/** The Mac's Agents (AgentPages.swift): what new chats start with, then when one is stuck. */
export function AgentsPage() {
  const { state } = useStore();
  return (
    <>
      <NewChatsSection defaults={state.agentDefaults} />
      <StuckSection settings={state.settings.stuck} />
    </>
  );
}

/**
 * What new chats start with, kept on the daemon and shared with the iPhone (B94): the model
 * menu has a section per engine, and the model chosen picks the engine; Thinking and
 * Permissions follow that model.
 */
function NewChatsSection({ defaults }: { defaults: AgentDefaults | null }) {
  const { state, actions } = useStore();
  const provider = defaults?.provider ?? CLAUDE;
  const catalog = catalogFor(state, provider);
  const model = defaults?.model ?? catalog.defaultModel;
  const levels = thinkingLevels(catalog, model);
  const permission = defaults?.permission_mode ?? "default";
  const loaded = defaults !== null;

  const save = (change: Partial<AgentDefaults>) => {
    if (defaults !== null) void actions.saveAgentDefaults({ ...defaults, ...change }, defaults);
  };

  const modelItems = (): MenuEntry[] =>
    modelSections(state, provider, true).flatMap((section): MenuEntry[] => {
      const head: MenuEntry[] = [{ type: "section", title: section.title }];
      if (section.detail !== "") head.push({ type: "note", text: section.detail });
      if (section.catalog.models.length === 0) {
        head.push({ title: "Models unavailable", disabled: true, onSelect: () => undefined });
      }
      return [
        ...head,
        ...section.catalog.models.map((info) => ({
          title: info.display_name,
          ...(info.description === "" ? {} : { detail: info.description }),
          checked: section.provider === provider && info.value === model,
          disabled: !section.available || section.unavailable?.includes(info.value) === true,
          warns: section.weak?.includes(info.value) === true,
          onSelect: () => {
            const own = catalogFor(state, section.provider);
            save({
              provider: section.provider,
              model: info.value,
              effort: effortAfterSwitching(own, defaults?.effort ?? null, info.value),
              permission_mode:
                permission === "auto" && !supportsAuto(own, info.value) ? "default" : permission,
            });
          },
        })),
      ];
    });

  const thinkingItems = (): MenuEntry[] => [
    { type: "section", title: "Thinking" },
    ...levels.map((level) => ({
      title: effortLabel(level),
      checked: defaults?.effort === level,
      onSelect: () => {
        save({ effort: level });
      },
    })),
  ];

  const modes = PERMISSIONS.filter((o) => o.value !== "auto" || supportsAuto(catalog, model));
  const permissionItems = (): MenuEntry[] => [
    { type: "section", title: "Permission mode" },
    ...modes.map((option) => ({
      title: option.label,
      ...(option.hint === undefined ? {} : { detail: option.hint }),
      checked: option.value === permission,
      onSelect: () => {
        save({ permission_mode: option.value });
      },
    })),
  ];

  const effort = defaults?.effort ?? null;
  return (
    <SettingsSection title="New chats">
      <SettingsRow label="Model">
        <Dropdown
          label="Model"
          title={loaded ? modelLabel(catalog, model) : "-"}
          items={modelItems}
          disabled={!loaded}
        />
      </SettingsRow>
      <SettingsRow label="Thinking">
        <Dropdown
          label="Thinking"
          title={
            effort !== null ? effortLabel(effort) : levels.length === 0 ? "Not available" : "-"
          }
          items={thinkingItems}
          disabled={!loaded || levels.length === 0}
        />
      </SettingsRow>
      <SettingsRow label="Permissions">
        <Dropdown
          label="Permissions"
          title={PERMISSIONS.find((o) => o.value === permission)?.label ?? permission}
          items={permissionItems}
          disabled={!loaded}
        />
      </SettingsRow>
      <SettingsRow label="Work in">
        <Segmented
          label="Work in"
          value={defaults?.mode ?? "in_place"}
          options={MODES}
          onChange={(mode) => {
            save({ mode });
          }}
        />
      </SettingsRow>
    </SettingsSection>
  );
}

/** When the daemon flags a running chat as stuck (D036). */
function StuckSection({ settings }: { settings: StuckSettings | null }) {
  const { actions } = useStore();
  return (
    <SettingsSection title="Stuck chats">
      {STUCK_THRESHOLDS.map((threshold) => {
        const value = settings?.[threshold.key] ?? 0;
        return (
          <SettingsRow key={threshold.key} label={threshold.title}>
            <Dropdown
              label={threshold.title}
              title={settings === null ? "-" : stuckLabel(threshold, value)}
              width={130}
              disabled={settings === null}
              items={() =>
                choiceItems(
                  stuckChoices(threshold, value),
                  value,
                  (choice) => stuckLabel(threshold, choice),
                  (choice) => {
                    if (settings !== null) {
                      void actions.saveSection(
                        "stuck",
                        { ...settings, [threshold.key]: choice },
                        settings,
                      );
                    }
                  },
                )
              }
            />
          </SettingsRow>
        );
      })}
    </SettingsSection>
  );
}
