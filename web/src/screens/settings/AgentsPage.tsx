import { Fragment } from "react";
import type {
  AgentDefaults,
  Effort,
  ModelOption,
  PermissionMode,
  SessionMode,
} from "../../api/types.ts";
import {
  CLAUDE,
  effortAfterSwitching,
  modelLabel,
  standardEffort,
  supportsAuto,
  thinkingLevels,
  type ModelCatalog,
} from "../../store/catalog.ts";
import { useStore } from "../../store/context.ts";
import { catalogFor, modelSections } from "../../store/selectors.ts";
import { effortLabel, PERMISSIONS } from "../chat/options.ts";
import { Loading, Section, SegRow, type Choice } from "./rows.tsx";
import { StuckChats } from "./StuckChats.tsx";

const MODES: Choice<SessionMode>[] = [
  { value: "in_place", label: "Current branch" },
  { value: "worktree", label: "New worktree" },
];

/** New chats and stuck chats (B81); each change is saved to the Mac at once. */
export function AgentsPage() {
  const { state } = useStore();
  const defaults = state.agentDefaults;
  return (
    <>
      {defaults === null ? <Loading title="New chats" /> : <Choices defaults={defaults} />}
      <StuckChats />
    </>
  );
}

// A model's choice in the menu: its engine and its value, which has no spaces.
const choiceOf = (provider: string, model: string) => `${provider} ${model}`;

/**
 * What new chats start with (B94, B102 items 27, 28): real choices only. The model menu has
 * a section per engine, and the model chosen picks the engine new chats run on; Thinking
 * and Permissions follow that model.
 */
function Choices({ defaults }: { defaults: AgentDefaults }) {
  const { state, actions } = useStore();
  const provider = defaults.provider ?? CLAUDE;
  const catalog = catalogFor(state, provider);
  const model = defaults.model ?? catalog.defaultModel;
  const sections = modelSections(state, provider, true);
  const levels = thinkingLevels(catalog, model);
  const effort = defaults.effort ?? standardEffort(levels);
  const permission = defaults.permission_mode ?? "default";
  const modes = PERMISSIONS.filter((o) => o.value !== "auto" || supportsAuto(catalog, model));
  const listed = sections.some(
    (section) => section.provider === provider && isListed(section.catalog, model),
  );
  const save = (change: Partial<AgentDefaults>) => {
    void actions.saveAgentDefaults({ ...defaults, ...change }, defaults);
  };
  const choose = (value: string) => {
    const at = value.indexOf(" ");
    const engine = value.slice(0, at);
    const chosen = value.slice(at + 1);
    const own = catalogFor(state, engine);
    save({
      provider: engine,
      model: chosen,
      effort: effortAfterSwitching(own, defaults.effort, chosen),
      permission_mode: permission === "auto" && !supportsAuto(own, chosen) ? "default" : permission,
    });
  };
  const items = (models: ModelOption[], engine: string) =>
    models.map((m) => (
      <option key={m.value} value={choiceOf(engine, m.value)}>
        {m.display_name}
      </option>
    ));
  return (
    <Section title="New chats">
      <div className="srow">
        <label htmlFor="default-model">Model</label>
        <select
          id="default-model"
          className="ssel"
          value={choiceOf(provider, model ?? "")}
          onChange={(event) => {
            choose(event.target.value);
          }}
        >
          {sections.map((section) =>
            sections.length === 1 ? (
              <Fragment key={section.provider}>
                {items(section.catalog.models, section.provider)}
              </Fragment>
            ) : (
              <optgroup
                key={section.provider}
                label={
                  section.detail === "" ? section.title : `${section.title} · ${section.detail}`
                }
              >
                {items(section.catalog.models, section.provider)}
              </optgroup>
            ),
          )}
          {!listed && (
            <option value={choiceOf(provider, model ?? "")}>{modelLabel(catalog, model)}</option>
          )}
        </select>
      </div>
      <div className="srow">
        <label htmlFor="default-effort">Thinking</label>
        {levels.length === 0 ? (
          <select id="default-effort" className="ssel" disabled value="">
            <option value="">Not available</option>
          </select>
        ) : (
          <select
            id="default-effort"
            className="ssel"
            value={String(effort)}
            onChange={(event) => {
              save({ effort: event.target.value as Effort });
            }}
          >
            {levels.map((level) => (
              <option key={level} value={level}>
                {effortLabel(level)}
              </option>
            ))}
            {effort !== null && !levels.includes(effort) && (
              <option value={effort}>{effortLabel(effort)}</option>
            )}
          </select>
        )}
      </div>
      <div className="srow">
        <label htmlFor="default-permission">Permissions</label>
        <select
          id="default-permission"
          className="ssel"
          value={permission}
          onChange={(event) => {
            save({ permission_mode: event.target.value as PermissionMode });
          }}
        >
          {modes.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
          {!modes.some((o) => o.value === permission) && (
            <option value={permission}>
              {PERMISSIONS.find((o) => o.value === permission)?.label ?? permission}
            </option>
          )}
        </select>
      </div>
      <SegRow
        label="Work in"
        value={defaults.mode}
        choices={MODES}
        onChange={(mode) => {
          save({ mode });
        }}
      />
    </Section>
  );
}

function isListed(catalog: ModelCatalog, model: string | null): boolean {
  return catalog.models.some((m) => m.value === model);
}
