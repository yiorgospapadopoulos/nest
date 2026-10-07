import { useState } from "react";
import type { BackgroundItem, BackgroundSummary } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { Tone } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

const TONES: Record<BackgroundItem["status"], Tone> = {
  running: "run",
  done: "done",
  failed: "fail",
};

/**
 * "N running · M completed" just above the composer, like Claude Code: subagents and
 * background commands, which can outlive the turn that started them. Expands to the list.
 */
export function BackgroundBar({ summary }: { summary: BackgroundSummary }) {
  const [open, setOpen] = useState(false);
  if (summary.running === 0 && summary.completed === 0) return null;
  const running = summary.items.filter((item) => item.status === "running");
  const finished = summary.items.filter((item) => item.status !== "running");
  return (
    <div className="bgw">
      <div className="bgbar gl">
        {open && (
          <div className="bgl">
            <Group label="Running" items={running} />
            <Group label="Completed" items={finished} />
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
          <span>
            {summary.running} running · {summary.completed} completed
          </span>
          <Icon name="chev" className="cv" />
        </button>
      </div>
    </div>
  );
}

function Group({ label, items }: { label: string; items: BackgroundItem[] }) {
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
                : item.status}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
