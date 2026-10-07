import { useId, useState } from "react";
import type { Approval } from "../../api/types.ts";
import { Markdown } from "../../ui/Markdown.tsx";
import { usePlan } from "./hooks.ts";

// Longer plans start clipped, with a "Show all" toggle.
const LONG_LINES = 16;
const LONG_CHARS = 1200;

function isLong(plan: string): boolean {
  return plan.split("\n").length > LONG_LINES || plan.length > LONG_CHARS;
}

/**
 * The plan Claude wrote in plan mode, with "Approve plan" and "Keep planning". Keeping
 * planning can carry an optional note for Claude.
 */
export function PlanForm({ approval }: { approval: Approval }) {
  const { busy, plan, approve, keepPlanning } = usePlan(approval);
  const [all, setAll] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const id = useId();
  const long = isLong(plan);

  return (
    <>
      <div className={long && !all ? "plan clip" : "plan"}>
        <Markdown text={plan} />
      </div>
      {long && (
        <button
          className="lnk2"
          aria-expanded={all}
          onClick={() => {
            setAll(!all);
          }}
        >
          {all ? "Show less" : "Show all"}
        </button>
      )}
      {note === null ? (
        <div className="acts">
          <button className="b b-pri" disabled={busy} onClick={() => void approve()}>
            Approve plan
          </button>
          <button
            className="b"
            disabled={busy}
            onClick={() => {
              setNote("");
            }}
          >
            Keep planning
          </button>
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void keepPlanning(note);
          }}
        >
          <label className="sr" htmlFor={id}>
            Note for Claude
          </label>
          <input
            id={id}
            className="fin"
            placeholder="What should change? (optional)"
            autoComplete="off"
            value={note}
            autoFocus
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
          <div className="acts">
            <button className="b b-pri" type="submit" disabled={busy}>
              Keep planning
            </button>
            <button
              className="b qb2"
              type="button"
              onClick={() => {
                setNote(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </>
  );
}
