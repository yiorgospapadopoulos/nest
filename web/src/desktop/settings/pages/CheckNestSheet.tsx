import { useMemo } from "react";
import type { SetupCheck } from "../../../api/types.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { FixAction, StepMark, TestNotification } from "../../setup/parts.tsx";
import type { Mark } from "../../setup/steps.ts";
import { useChecks } from "../../setup/useChecks.ts";
import { Button } from "../../ui/controls.tsx";
import { Note } from "../rows.tsx";

const MARKS: Record<SetupCheck["state"], Mark> = {
  ok: "ok",
  missing: "now",
  warning: "now",
  not_applicable: "todo",
};

/** A check with nothing to say, such as Dictation on Linux, does not apply here at all. */
const shown = (check: SetupCheck) =>
  check.state !== "not_applicable" || check.message !== "" || check.detail !== null;

function CheckRow({ check }: { check: SetupCheck }) {
  // The daemon cannot tell whether a notification reaches this desktop; the app can.
  const appAnswers = check.id === "notifications";
  const message = appAnswers ? "" : check.message;
  return (
    <div className="su-check">
      <StepMark mark={MARKS[check.state]} />
      <div className="su-check-head">
        {check.title}
        {check.detail !== null && <span>{check.detail}</span>}
      </div>
      {(message !== "" || check.fix !== null || appAnswers) && (
        <div className="su-check-more">
          {message !== "" && <p className="su-line">{message}</p>}
          {check.fix !== null && <FixAction fix={check.fix} />}
          {appAnswers && <TestNotification />}
        </div>
      )}
    </div>
  );
}

/** Every check with its message and fix, the same list `nest doctor` prints. */
export function CheckNestSheet({ onClose }: { onClose: () => void }) {
  const { checks, checking, refresh } = useChecks();
  const list = useMemo(() => checks?.filter(shown) ?? null, [checks]);
  return (
    <SheetFrame
      title="Check Nest"
      onClose={onClose}
      footer={
        <>
          {checking && <Fireflies />}
          <Button size="large" disabled={checking} onClick={refresh}>
            Check again
          </Button>
        </>
      }
    >
      {list === null ? (
        !checking && <Note>The checks could not run.</Note>
      ) : (
        <div className="su-checks">
          {list.map((check) => (
            <CheckRow key={check.id} check={check} />
          ))}
        </div>
      )}
    </SheetFrame>
  );
}
