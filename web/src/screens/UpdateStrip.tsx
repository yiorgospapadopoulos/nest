import { useState } from "react";
import { useStore } from "../store/context.ts";
import {
  engineChange,
  restartQuestion,
  updateStrip,
  useUpdateRestart,
  type UpdateStrip as Strip,
} from "../store/updates.ts";
import { Icon } from "../ui/Icon.tsx";
import { useHeightVar } from "../ui/useHeightVar.ts";
import { Confirm } from "./pixies/Confirm.tsx";

/** Just above the tab bar, over the tab's content: an update ready, or a notice. */
export function UpdateStrip() {
  const { state } = useStore();
  const strip = updateStrip(state.updates, "phone");
  if (strip === null) return null;
  return strip.kind === "notice" ? <Notice text={strip.text} /> : <Ready strip={strip} />;
}

function Notice({ text }: { text: string }) {
  const { actions } = useStore();
  const box = useHeightVar("--update-strip");
  return (
    <div ref={box} className="upstrip upstrip-notice" role="status">
      <p>{text}</p>
      <button
        className="tdis"
        aria-label="Dismiss"
        onClick={() => void actions.dismissUpdateNotice()}
      >
        <Icon name="x" />
      </button>
    </div>
  );
}

function Ready({ strip }: { strip: Extract<Strip, { kind: "ready" }> }) {
  const { actions } = useStore();
  const box = useHeightVar("--update-strip");
  const relaunch = useUpdateRestart("relaunch");
  const [open, setOpen] = useState(false);
  const { engines, relaunching } = strip;
  return (
    <div ref={box} className="upstrip">
      {open && engines.length > 0 && (
        <ul>
          {engines.map((engine) => (
            <li key={engine.id}>{engineChange(engine)}</li>
          ))}
        </ul>
      )}
      <div className="upstrip-row">
        <button className="b b-pri" disabled={relaunching} onClick={() => void relaunch.start()}>
          {relaunching ? "Relaunching..." : "Relaunch to update"}
        </button>
        <button
          className="upstrip-more"
          aria-label="What's updating"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          <Icon name={open ? "chev" : "chevr"} />
        </button>
        <button
          className="tdis upstrip-hide"
          aria-label="Hide for now"
          disabled={relaunching}
          onClick={actions.hideUpdateStrip}
        >
          <Icon name="x" />
        </button>
      </div>
      {relaunch.asking !== null && (
        <Confirm
          {...restartQuestion("relaunch", relaunch.asking)}
          neutral
          onConfirm={relaunch.confirm}
          onClose={relaunch.cancel}
        />
      )}
    </div>
  );
}
