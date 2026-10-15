import type { AgentDefaults, Effort, PermissionMode, SessionMode } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import {
  CLAUDE_CODE_MODE,
  CLAUDE_DEFAULT,
  effortLabel,
  labelOf,
  modelDefaultEffort,
  permissionOptions,
  takesAuto,
  thinkingLevels,
} from "../chat/options.ts";

const MODES: { mode: SessionMode; label: string }[] = [
  { mode: "in_place", label: "Work on current branch" },
  { mode: "worktree", label: "New worktree" },
];

/** What new chats use unless the composer chooses otherwise; saved to the Mac at once. */
export function AgentDefaultsCard() {
  const { state } = useStore();
  const defaults = state.agentDefaults;
  return (
    <section aria-labelledby="agent-defaults-title">
      <h2 className="pg-h" id="agent-defaults-title">
        Agent defaults
      </h2>
      {defaults === null ? (
        <div className="lgrp gl pad note">Loading...</div>
      ) : (
        <Choices defaults={defaults} />
      )}
    </section>
  );
}

function Choices({ defaults }: { defaults: AgentDefaults }) {
  const { state, actions } = useStore();
  const models = state.models ?? [];
  const model = defaults.model ?? CLAUDE_DEFAULT;
  const levels = thinkingLevels(state.models, model);
  const save = (change: Partial<AgentDefaults>) => {
    const next = { ...defaults, ...change };
    // A thinking level the newly chosen model does not take is dropped.
    if (next.effort !== null && !thinkingLevels(state.models, next.model).includes(next.effort)) {
      next.effort = null;
    }
    // So is Auto, which goes back to Claude Code's own mode; only a known model list says
    // the model does not take it.
    if (
      next.permission_mode === "auto" &&
      state.models !== null &&
      !takesAuto(state.models, next.model)
    ) {
      next.permission_mode = null;
    }
    void actions.saveAgentDefaults(next, defaults);
  };
  const listed = models.some((m) => m.value === model);
  // A saved mode the model list does not offer (yet) still shows as it is.
  const modes = permissionOptions(state.models, model);
  const modeListed =
    defaults.permission_mode === null || modes.some((o) => o.value === defaults.permission_mode);
  return (
    <div className="lgrp gl">
      <div className="srow">
        <label htmlFor="default-model">Model</label>
        <select
          id="default-model"
          className="ssel"
          value={model}
          onChange={(event) => {
            save({ model: event.target.value });
          }}
        >
          {models.map((m) => (
            <option key={m.value} value={m.value}>
              {m.display_name}
            </option>
          ))}
          {!listed && <option value={model}>{model}</option>}
        </select>
      </div>
      <div className="srow">
        <label htmlFor="default-effort">Thinking</label>
        {levels.length === 0 ? (
          <select id="default-effort" className="ssel" disabled value="">
            <option value="">Not available for this model</option>
          </select>
        ) : (
          <select
            id="default-effort"
            className="ssel"
            value={defaults.effort ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              save({ effort: value === "" ? null : (value as Effort) });
            }}
          >
            <option value="">{modelDefaultEffort(state.models, model)}</option>
            {levels.map((level) => (
              <option key={level} value={level}>
                {effortLabel(level)}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="srow">
        <label htmlFor="default-permission">Permission mode</label>
        <select
          id="default-permission"
          className="ssel"
          value={defaults.permission_mode ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            save({ permission_mode: value === "" ? null : (value as PermissionMode) });
          }}
        >
          <option value="">{CLAUDE_CODE_MODE}</option>
          {modes.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
          {!modeListed && (
            <option value={String(defaults.permission_mode)}>
              {labelOf("permission", defaults.permission_mode, state.models)}
            </option>
          )}
        </select>
      </div>
      <div className="srow col">
        <span id="default-mode-label">New chats work in</span>
        <div className="mseg" role="group" aria-labelledby="default-mode-label">
          {MODES.map(({ mode, label }) => (
            <button
              key={mode}
              aria-pressed={defaults.mode === mode}
              onClick={() => {
                save({ mode });
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
