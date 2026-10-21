import { useState } from "react";
import type { BackgroundSummary } from "../../api/types.ts";
import { ago } from "../../format.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { StopTask } from "./StopTask.tsx";
import type { Stopper } from "./useStopTask.ts";

/**
 * "N running tasks" just above the composer while any of the chat's subagents or
 * background commands run, as the Mac's (B76): it opens upwards to the running tasks, each
 * with Stop (B59). Finished tasks are not listed; running work glows (D045).
 */
export function BackgroundBar({
  summary,
  stopper = null,
}: {
  summary: BackgroundSummary;
  stopper?: Stopper | null;
}) {
  const [open, setOpen] = useState(false);
  const running = summary.items.filter((item) => item.status === "running");
  const hidden = running.length === 0;
  // It comes back collapsed.
  if (hidden && open) setOpen(false);
  if (hidden) return null;
  const label = running.length === 1 ? "1 running task" : `${String(running.length)} running tasks`;
  const now = new Date();
  return (
    <div className="bgw">
      <div className="bgbar">
        {open && (
          <section className="bgg">
            <h3 className="bgh">Running</h3>
            <ul aria-label="Running">
              {running.map((item) => (
                <li key={item.id}>
                  <Dot tone="run" />
                  <Icon name={item.kind === "bash" ? "term" : "bot"} />
                  <b>{item.name}</b>
                  <span className="mono">{item.description ?? ""}</span>
                  <span className="mt2">
                    {item.started_at === null ? "" : ago(item.started_at, now)}
                  </span>
                  <StopTask id={item.id} name={item.name} stopper={stopper} />
                </li>
              ))}
            </ul>
          </section>
        )}
        <button
          className="bgsum"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          <Dot tone="run" />
          <span className="glow">{label}</span>
          <Icon name="chev" className="cv" />
        </button>
      </div>
    </div>
  );
}
