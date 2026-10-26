import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import type { RunStatus } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { ansiSpans, type AnsiSpan } from "./ansi.ts";
import type { ChatPlace } from "./place.ts";
import { PlaceMark } from "./PlaceMarks.tsx";
import { failedCode, isAlive, portsText } from "./run.ts";
import { isAtBottom } from "./scrollFollow.ts";

interface Props {
  sessionId: string;
  status: RunStatus;
  onOpen: () => void;
}

/**
 * The header's dev server button (B108): Run starts the repo's run command and shows its
 * output; while it runs, a stop square. A run that failed says so; it opens the output.
 */
export function RunButton({ sessionId, status, onOpen }: Props) {
  const { actions } = useStore();
  if (isAlive(status)) {
    return (
      <button
        className="ib rstop"
        aria-label={`Stop ${String(status.command)}`}
        onClick={() => void actions.runControl(sessionId, "stop")}
      >
        <Icon name="stop" />
      </button>
    );
  }
  const failed = failedCode(status);
  if (failed !== null) {
    return (
      <button className="b rbtn bad" aria-haspopup="dialog" onClick={onOpen}>
        <Icon name="play" />
        Exited {failed}
      </button>
    );
  }
  return (
    <button
      className="b rbtn"
      onClick={() => {
        onOpen();
        void actions.runControl(sessionId, "start");
      }}
    >
      <Icon name="play" />
      Run
    </button>
  );
}

/** The header's line under the title: where the chat works, then the run's ports. */
export function RunLine({
  place,
  status,
  onOpen,
}: {
  place: ChatPlace | null;
  status: RunStatus;
  onOpen: () => void;
}) {
  const ports = status.listening;
  const live = ports.length > 0;
  return (
    <>
      <PlaceMark place={place} />
      {(live || status.state === "starting") && (
        <button
          className="rline"
          aria-haspopup="dialog"
          aria-label={live ? `Ports ${ports.join(", ")}` : undefined}
          onClick={onOpen}
        >
          {live ? (
            <>
              <span className="rlive" aria-hidden="true" />
              {portsText(ports)}
            </>
          ) : (
            "Starting"
          )}
        </button>
      )}
    </>
  );
}

/** The run's output, live, with restart and stop. */
export function RunSheet({
  sessionId,
  status,
  onClose,
}: {
  sessionId: string;
  status: RunStatus;
  onClose: () => void;
}) {
  const { state, actions } = useStore();
  // An available run always has its folder.
  const folder = String(status.folder);
  const alive = isAlive(status);
  const text = state.runOutput[folder] ?? "";
  const spans = useMemo(() => ansiSpans(text), [text]);
  const pre = useRef<HTMLPreElement>(null);
  // Kept at the end unless the user scrolled up to read.
  const follow = useRef(true);

  // Loaded again when the run starts again: the daemon starts its output afresh.
  useEffect(() => {
    void actions.openRunOutput(sessionId, folder);
  }, [actions, sessionId, folder, status.started_at]);
  useEffect(
    () => () => {
      actions.closeRunOutput(folder);
    },
    [actions, folder],
  );
  useLayoutEffect(() => {
    const box = pre.current;
    if (box !== null && follow.current) box.scrollTop = box.scrollHeight;
  }, [spans]);

  return (
    <Sheet
      title={String(status.command)}
      onClose={onClose}
      trailing={
        <div className="rsh-acts">
          <button
            className="ib"
            aria-label={alive ? "Restart" : "Run again"}
            onClick={() => void actions.runControl(sessionId, alive ? "restart" : "start")}
          >
            <Icon name="restart" />
          </button>
          <button
            className="b b-no"
            disabled={!alive}
            onClick={() => void actions.runControl(sessionId, "stop")}
          >
            <Icon name="stop" />
            Stop
          </button>
        </div>
      }
    >
      <pre
        ref={pre}
        className="rout"
        aria-label="Output"
        tabIndex={0}
        // Opens on the output, so a stray Enter restarts nothing.
        data-autofocus
        onScroll={(event) => {
          const box = event.currentTarget;
          follow.current = isAtBottom({
            offset: box.scrollTop,
            viewport: box.clientHeight,
            content: box.scrollHeight,
          });
        }}
      >
        {spans.map((span, index) => (
          <span key={index} className={spanClass(span)}>
            {span.text}
          </span>
        ))}
      </pre>
    </Sheet>
  );
}

/** A span's colour (as `a31`) and weight (`ab`) classes, if it has any. */
function spanClass({ color, bold }: AnsiSpan): string | undefined {
  const names = [...(color === null ? [] : [`a${String(color)}`]), ...(bold ? ["ab"] : [])];
  return names.length === 0 ? undefined : names.join(" ");
}
