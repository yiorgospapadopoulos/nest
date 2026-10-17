import { useState } from "react";
import type { TrackedAgent } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { toolIcon } from "../../ui/toolIcon.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { Fireflies } from "../../ui/Fireflies.tsx";

const TONES: Record<TrackedAgent["status"], Tone> = {
  running: "run",
  done: "done",
  failed: "fail",
};
const STEPS_SHOWN = 5;

/** The main agent and its subagents, each expanding to its last steps. */
export function AgentsSheet({ agents, onClose }: { agents: TrackedAgent[]; onClose: () => void }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <Sheet title="Agents" onClose={onClose}>
      {agents.length === 0 && <p className="note">No agents have run yet.</p>}
      <div className="agl">
        {agents.map((agent) => {
          const open = expanded === agent.id;
          const steps = agent.steps.slice(-STEPS_SHOWN);
          return (
            <div key={agent.id} className="agc">
              <button
                className="agr"
                aria-expanded={open}
                onClick={() => {
                  setExpanded(open ? null : agent.id);
                }}
              >
                <Dot tone={TONES[agent.status]} />
                <b>{agent.name}</b>
                <span className="mt2">
                  {agent.status === "running" && agent.started_at !== null
                    ? ago(agent.started_at, new Date())
                    : agent.status}
                </span>
                <span className="mono">{agent.activity ?? agent.description ?? ""}</span>
              </button>
              {open && (
                <ul className="aglog" aria-label="Last steps">
                  {steps.length === 0 && <li className="lr">No steps yet</li>}
                  {steps.map((step, i) => (
                    <li key={step.id}>
                      {step.result === null &&
                      agent.status === "running" &&
                      i === steps.length - 1 ? (
                        <Fireflies size={10} />
                      ) : (
                        <Icon name={toolIcon(step.tool)} />
                      )}
                      <span className="la">
                        <b>{step.tool}</b> {step.arg}
                      </span>
                      <span className="lr">{step.result ?? "running"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </Sheet>
  );
}
