import { useState } from "react";
import type { CheckFix } from "../../api/types.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { useBridge } from "../context.ts";
import { Button } from "../ui/controls.tsx";
import type { Mark } from "./steps.ts";
import "./setup.css";
import { useCopy } from "./useCopy.ts";

const MARK_NAMES: Record<Mark, string> = {
  ok: "Done",
  todo: "Not done",
  now: "Open now",
  skipped: "Skipped",
};

/** A step's round mark: told apart by shape, never by colour alone. */
export function StepMark({ mark }: { mark: Mark }) {
  return (
    <span className={`su-mark ${mark}`} role="img" aria-label={MARK_NAMES[mark]}>
      {mark === "ok" && (
        <svg viewBox="0 0 14 14" aria-hidden="true">
          <path d="M4 7.2 6.2 9.4 10 5" />
        </svg>
      )}
    </span>
  );
}

/** One line to paste, with Copy inside its box. */
export function CommandBox({ command }: { command: string }) {
  const { copied, copy } = useCopy(command);
  return (
    <div className="su-cmd">
      <code>{command}</code>
      <Button onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
    </div>
  );
}

/** A check's way out: the command to paste, or the page to open. */
export function FixAction({ fix }: { fix: CheckFix }) {
  const bridge = useBridge();
  if (fix.kind === "command") return <CommandBox command={fix.value} />;
  return (
    <div>
      <Button
        onClick={() => {
          void bridge.openExternal(fix.value);
        }}
      >
        Open
      </Button>
    </div>
  );
}

export function CheckAgain({ checking, onCheck }: { checking: boolean; onCheck: () => void }) {
  return (
    <div className="su-again">
      <Button disabled={checking} onClick={onCheck}>
        Check again
      </Button>
      {checking && <Fireflies />}
    </div>
  );
}

const TEST_TITLE = "Nest";
const TEST_BODY = "Notifications work.";

/** Sends a real notification through the app; the answer the daemon cannot give. */
export function TestNotification({ onSent }: { onSent?: () => void }) {
  const bridge = useBridge();
  const [sent, setSent] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const send = () => {
    bridge.notify(TEST_TITLE, TEST_BODY).then(
      () => {
        setSent(true);
        setFailure(null);
        onSent?.();
      },
      (error: unknown) => {
        setSent(false);
        setFailure(error instanceof Error ? error.message : String(error));
      },
    );
  };
  return (
    <div className="su-again">
      <Button onClick={send}>Send a test notification</Button>
      {sent && <span className="su-quiet">Sent</span>}
      {failure !== null && <span className="su-fail">{failure}</span>}
    </div>
  );
}
