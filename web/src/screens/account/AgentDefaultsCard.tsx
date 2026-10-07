import type { AgentDefaults, Effort, PermissionMode, SessionMode } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import {
  CLAUDE_DEFAULT,
  effortLabel,
  NO_THINKING,
  PERMISSIONS,
  thinkingLevels,
} from "../chat/options.ts";

const MODES: { mode: SessionMode; label: string }[] = [
  { mode: "in_place", label: "In place" },
  { mode: "worktree", label: "Worktree" },
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
    void actions.saveAgentDefaults(next, defaults);
  };
  const listed = models.some((m) => m.value === model);
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
            <option value="">{NO_THINKING}</option>
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
            <option value="">Model default</option>
            {levels.map((level) => (
              <option key={level} value={level}>
                {effortLabel(level)}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="srow">
        <label htmlFor="default-permission">Permission</label>
        <select
          id="default-permission"
          className="ssel"
          value={defaults.permission_mode}
          onChange={(event) => {
            save({ permission_mode: event.target.value as PermissionMode });
          }}
        >
          {PERMISSIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="srow">
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
