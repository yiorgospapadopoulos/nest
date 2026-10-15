import { useState } from "react";
import type { BackgroundItem, BackgroundSummary } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { StopTask } from "./StopTask.tsx";
import type { Stopper } from "./useStopTask.ts";

const TONES: Record<BackgroundItem["status"], Tone> = {
  running: "run",
  done: "done",
  failed: "fail",
};
// A task's status in the Mac's words, where no start time is shown instead.
const STATUS: Record<BackgroundItem["status"], string> = {
  running: "Running",
  done: "Done",
  failed: "Failed",
};

/**
 * "N running · M completed" just above the composer, like Claude Code: the subagents and
 * background commands of the current exchange (`exchangeBackground`), which can outlive
 * the turn that started them. Expands to the list. Before any completes it reads "1 running
 * task" or "N running tasks", as on the Mac;
 * running work glows (D045). Each running task can be stopped on its own (B59).
 */
export function BackgroundBar({
  summary,
  stopper = null,
}: {
  summary: BackgroundSummary;
  stopper?: Stopper | null;
}) {
  const [open, setOpen] = useState(false);
  const hidden = summary.running === 0 && summary.completed === 0;
  // It comes back collapsed.
  if (hidden && open) setOpen(false);
  if (hidden) return null;
  const running = summary.items.filter((item) => item.status === "running");
  const finished = summary.items.filter((item) => item.status !== "running");
  return (
    <div className="bgw">
      <div className="bgbar gl">
        {open && (
          <div className="bgl">
            <Group label="Running" items={running} stopper={stopper} />
            <Group label="Completed" items={finished} stopper={null} />
          </div>
        )}
        <button
          className="bgsum"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          <Dot tone={summary.running > 0 ? "run" : "done"} />
          <span className={summary.running > 0 ? "glow" : undefined}>{label(summary)}</span>
          <Icon name="chev" className="cv" />
        </button>
      </div>
    </div>
  );
}

function label({ running, completed }: BackgroundSummary): string {
  if (completed === 0) return running === 1 ? "1 running task" : `${String(running)} running tasks`;
  return `${String(running)} running · ${String(completed)} completed`;
}

interface GroupProps {
  label: string;
  items: BackgroundItem[];
  stopper: Stopper | null;
}

function Group({ label, items, stopper }: GroupProps) {
  if (items.length === 0) return null;
  const now = new Date();
  return (
    <section className="bgg">
      <h3 className="bgh">{label}</h3>
      <ul aria-label={label}>
        {items.map((item) => (
          <li key={item.id}>
            <Dot tone={TONES[item.status]} />
            <Icon name={item.kind === "bash" ? "term" : "bot"} />
            <b>{item.name}</b>
            <span className="mono">{item.description ?? ""}</span>
            <span className="mt2">
              {item.status === "running" && item.started_at !== null
                ? ago(item.started_at, now)
                : STATUS[item.status]}
            </span>
            <StopTask id={item.id} name={item.name} stopper={stopper} />
          </li>
        ))}
      </ul>
    </section>
  );
}
