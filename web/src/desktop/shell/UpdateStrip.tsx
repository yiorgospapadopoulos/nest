import { useState } from "react";
import { useStore } from "../../store/context.ts";
import {
  appChange,
  engineChange,
  restartQuestion,
  updateStrip,
  type UpdateStrip as Strip,
} from "../../store/updates.ts";
import { Icon } from "../../ui/Icon.tsx";
import { useHeightVar } from "../../ui/useHeightVar.ts";
import { Confirm } from "../sheets/Alert.tsx";
import { Button } from "../ui/controls.tsx";
import "./frame/frame.css";
import { useRelaunch } from "./useRelaunch.ts";

/** Pinned to the bottom of the left bar, over the list: an update ready, or a notice. */
export function UpdateStrip() {
  const { state } = useStore();
  const strip = updateStrip(state.updates, "app");
  if (strip === null) return null;
  return strip.kind === "notice" ? <Notice text={strip.text} /> : <Ready strip={strip} />;
}

function Notice({ text }: { text: string }) {
  const { actions } = useStore();
  const box = useHeightVar("--update-strip");
  return (
    <div ref={box} className="fr-update fr-unotice" role="status">
      <p>{text}</p>
      <Button
        kind="plain"
        iconOnly
        aria-label="Dismiss"
        onClick={() => void actions.dismissUpdateNotice()}
      >
        <Icon name="x" />
      </Button>
    </div>
  );
}

function Ready({ strip }: { strip: Extract<Strip, { kind: "ready" }> }) {
  const { actions } = useStore();
  const box = useHeightVar("--update-strip");
  const relaunch = useRelaunch();
  const [open, setOpen] = useState(false);
  const { app, engines, relaunching } = strip;
  const question = relaunch.asking === null ? null : restartQuestion("relaunch", relaunch.asking);
  return (
    <div ref={box} className="fr-update">
      {open && (app !== null || engines.length > 0) && (
        <ul>
          {app !== null && (
            <li>
              {appChange(app)}
              {app.notes !== "" && <p className="fr-unotes">{app.notes}</p>}
            </li>
          )}
          {engines.map((engine) => (
            <li key={engine.id}>{engineChange(engine)}</li>
          ))}
        </ul>
      )}
      <div className="fr-urow">
        <Button kind="primary" disabled={relaunching} onClick={() => void relaunch.start()}>
          {relaunching ? "Relaunching..." : "Relaunch to update"}
        </Button>
        <button
          className="fr-umore"
          aria-label="What's updating"
          title="What's updating"
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          <Icon name={open ? "chev" : "chevr"} />
        </button>
        <Button
          kind="plain"
          iconOnly
          className="fr-uhide"
          aria-label="Hide for now"
          title="Hide for now"
          disabled={relaunching}
          onClick={actions.hideUpdateStrip}
        >
          <Icon name="x" />
        </Button>
      </div>
      {question !== null && (
        <Confirm
          title={question.title}
          message={question.about}
          action={question.action}
          onConfirm={relaunch.confirm}
          onClose={relaunch.cancel}
        />
      )}
    </div>
  );
}

/** The squeezed bar's sign of the strip; a click on the rail opens the bar. */
export function UpdateRailDot() {
  const { state } = useStore();
  const strip = updateStrip(state.updates, "app");
  if (strip === null) return null;
  const title = strip.kind === "notice" ? strip.text : "Update available";
  return <span className="fr-udot" title={title} />;
}
