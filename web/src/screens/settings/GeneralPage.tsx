import { useEffect, useState } from "react";
import { useStore } from "../../store/context.ts";
import {
  readyUpdate,
  restartQuestion,
  updateChanges,
  useUpdateRestart,
} from "../../store/updates.ts";
import { Confirm } from "../pixies/Confirm.tsx";
import { modelChoices, useVoiceSettings, voiceStateLabel } from "../chat/voice/useVoiceSettings.ts";
import { Row, Section, SelectRow, Status } from "./rows.tsx";

type Phase = "idle" | "confirm" | "restarting" | "failed";

/** Nest itself: the version and Restart (B81), and voice input (B154). Storage has its own
 * page (B86). */
export function GeneralPage() {
  return (
    <>
      <VoiceSection />
      <NestSection />
    </>
  );
}

/** The mic's model, downloaded on the computer Nest runs on (B154). */
function VoiceSection() {
  const { status, choose, download, remove } = useVoiceSettings();
  const [confirm, setConfirm] = useState(false);
  if (status === null) return null;
  const shown = voiceStateLabel(status);
  return (
    <Section title="Voice input">
      <SelectRow
        label="Model"
        value={status.model}
        choices={modelChoices(status)}
        disabled={status.state === "installing"}
        onChange={choose}
      />
      <Row label="State">
        <Status tone={shown.tone} label={shown.label} />
      </Row>
      {status.detail !== null && <p className="srow note">{status.detail}</p>}
      <Row label={status.state === "ready" ? "Remove the download" : "Download"}>
        {status.state === "ready" ? (
          <button
            className="b"
            onClick={() => {
              setConfirm(true);
            }}
          >
            Remove
          </button>
        ) : (
          <button className="b" disabled={status.state === "installing"} onClick={download}>
            {status.state === "install_failed" ? "Try again" : "Download"}
          </button>
        )}
      </Row>
      {confirm && (
        <Confirm
          title="Remove voice input?"
          about="The mic asks to download it again the next time."
          action="Remove"
          onConfirm={remove}
          onClose={() => {
            setConfirm(false);
          }}
        />
      )}
    </Section>
  );
}

/** The version, and Restart: the daemon restarts, then the page loads again. */
function NestSection() {
  const { actions } = useStore();
  const [version, setVersion] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const restarting = phase === "restarting";

  useEffect(() => {
    let live = true;
    void actions.version().then((found) => {
      if (live) setVersion(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const restart = async () => {
    setPhase("restarting");
    const result = await actions.restartService();
    if (result === "back") window.location.reload();
    else setPhase(result === null ? "idle" : "failed");
  };

  return (
    <Section title="Nest">
      <Row label="Version">
        <span className="sval mono">{version ?? "..."}</span>
      </Row>
      <Row label="Restart Nest">
        <button
          className="b"
          disabled={restarting}
          onClick={() => {
            setPhase("confirm");
          }}
        >
          {restarting ? "Restarting..." : "Restart"}
        </button>
      </Row>
      <UpdateRow />
      <UndoUpdateRow />
      {phase === "failed" && (
        <p className="srow note" role="alert">
          Nest did not come back. Check that the Mac is awake, then reload.
        </p>
      )}
      {phase === "confirm" && (
        <Confirm
          title="Restart Nest?"
          about="Running turns are interrupted. They can be resumed after the restart."
          action="Restart"
          onConfirm={() => void restart()}
          onClose={() => {
            setPhase("idle");
          }}
        />
      )}
    </Section>
  );
}

/** The strip's update and button, here whether or not the strip was hidden. */
function UpdateRow() {
  const { state } = useStore();
  const relaunch = useUpdateRestart("relaunch");
  const ready = readyUpdate(state.updates, "phone");
  if (ready === null) return null;
  return (
    <>
      <Row label="Update available">
        <span className="sval mono lines">{updateChanges(ready)}</span>
        <button className="b" disabled={ready.relaunching} onClick={() => void relaunch.start()}>
          {ready.relaunching ? "Relaunching..." : "Relaunch to update"}
        </button>
      </Row>
      {relaunch.asking !== null && (
        <Confirm
          {...restartQuestion("relaunch", relaunch.asking)}
          neutral
          onConfirm={relaunch.confirm}
          onClose={relaunch.cancel}
        />
      )}
    </>
  );
}

/** Back to the engines before the last update, while there are any to go back to. */
function UndoUpdateRow() {
  const { state } = useStore();
  const undo = useUpdateRestart("undo");
  const undoing = undo.restarting === "undo";
  if (state.updates.status?.can_undo !== true && !undoing) return null;
  return (
    <>
      <Row label="Undo update">
        <button className="b" disabled={undo.restarting !== null} onClick={() => void undo.start()}>
          {undoing ? "Undoing..." : "Undo"}
        </button>
      </Row>
      {undo.asking !== null && (
        <Confirm
          {...restartQuestion("undo", undo.asking)}
          neutral
          onConfirm={undo.confirm}
          onClose={undo.cancel}
        />
      )}
    </>
  );
}
