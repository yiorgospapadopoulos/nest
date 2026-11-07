import { useEffect, useState } from "react";
import type { SetupReport } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import {
  readyUpdate,
  restartQuestion,
  updateChanges,
  useUpdateRestart,
} from "../../../store/updates.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import type { LinuxSettings } from "../../bridge.ts";
import { useApi, useBridge } from "../../context.ts";
import { useRelaunch } from "../../shell/useRelaunch.ts";
import { Button, Toggle } from "../../ui/controls.tsx";
import { Alert } from "../../sheets/Alert.tsx";
import { appAnswers } from "./appAnswers.ts";
import { BugReportSheet } from "./BugReportSheet.tsx";
import { CheckNestSheet } from "./CheckNestSheet.tsx";
import {
  Failure,
  SettingsListRow,
  SettingsRow,
  SettingsSection,
  SwitchRow,
  Value,
} from "../rows.tsx";

/**
 * The Mac's General (GeneralPages.swift): the sidebar's switch, this computer's, Nest, then
 * Setup, Help and Uninstall, each in a section of its own (B130).
 */
export function GeneralPage() {
  const { state, actions } = useStore();
  return (
    <>
      <SettingsSection title="Sidebar">
        <SwitchRow
          label="Show automated chats"
          on={state.showAutomated}
          onChange={(on) => void actions.setShowAutomated(on)}
        />
      </SettingsSection>
      <LinuxSection />
      <SettingsSection title="Nest">
        <VersionRow />
        <RestartRow />
        <UpdateRow />
        <UndoUpdateRow />
      </SettingsSection>
      <SetupSection />
      <HelpSection />
      <UninstallSection />
    </>
  );
}

/** Every check, what is done and what is missing; the guide itself shows only at first start. */
function SetupSection() {
  const [open, setOpen] = useState(false);
  return (
    <SettingsSection title="Setup">
      <SettingsRow label="Set up Nest">
        <Button
          onClick={() => {
            setOpen(true);
          }}
        >
          Open
        </Button>
      </SettingsRow>
      {open && (
        <CheckNestSheet
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </SettingsSection>
  );
}

/** A bug report, read in full before anything else. */
function HelpSection() {
  const { actions } = useStore();
  const api = useApi();
  const bridge = useBridge();
  const [reporting, setReporting] = useState(false);
  const [report, setReport] = useState<SetupReport | null>(null);
  const makeReport = () => {
    setReporting(true);
    appAnswers(bridge)
      .then((answers) => api.setupReport(answers))
      .then(setReport, (error: unknown) => {
        actions.toast(error instanceof Error ? error.message : String(error), "error");
      })
      .finally(() => {
        setReporting(false);
      });
  };
  return (
    <SettingsSection title="Help">
      <SettingsRow label="Report a bug">
        {reporting && <Fireflies />}
        <Button disabled={reporting} onClick={makeReport}>
          Report
        </Button>
      </SettingsRow>
      {report !== null && (
        <BugReportSheet
          report={report}
          onClose={() => {
            setReport(null);
          }}
        />
      )}
    </SettingsSection>
  );
}

/**
 * Uninstall Nest, on a released install only (B130): `nest uninstall` runs on its own, so
 * it outlives the app and the service, and the app quits. Chats, settings and secrets stay
 * unless the user chooses to delete them too.
 */
function UninstallSection() {
  const { actions } = useStore();
  const bridge = useBridge();
  const [released, setReleased] = useState(false);
  const [asking, setAsking] = useState(false);
  const [deleteData, setDeleteData] = useState(false);
  useEffect(() => {
    let live = true;
    void bridge
      .installState()
      .then((found) => {
        if (live) setReleased(found?.released === true);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [bridge]);
  if (!released) return null;
  const uninstall = () => {
    bridge.uninstall(deleteData).catch((error: unknown) => {
      actions.toast(error instanceof Error ? error.message : String(error), "error");
    });
  };
  return (
    <SettingsSection title="Uninstall">
      <SettingsRow label="Uninstall Nest">
        <Button
          kind="destructive"
          onClick={() => {
            setDeleteData(false);
            setAsking(true);
          }}
        >
          Uninstall
        </Button>
      </SettingsRow>
      {asking && (
        <Alert
          title="Uninstall Nest?"
          message={
            deleteData
              ? "Nest, its background service, and your chats, settings and secrets are deleted."
              : "Nest and its background service are removed. Your chats, settings and secrets stay."
          }
          actions={[{ title: "Uninstall", kind: "destructive", onSelect: uninstall }]}
          onClose={() => {
            setAsking(false);
          }}
        >
          <div className="dks-alertopt">
            <span>Also delete chats, settings and secrets</span>
            <Toggle
              label="Also delete chats, settings and secrets"
              checked={deleteData}
              onChange={setDeleteData}
            />
          </div>
        </Alert>
      )}
    </SettingsSection>
  );
}

/** The desktop app's own switches, kept by the Tauri side. */
function LinuxSection() {
  const bridge = useBridge();
  const [settings, setSettings] = useState<LinuxSettings | null>(null);
  useEffect(() => {
    let live = true;
    void bridge.settings().then((found) => {
      if (live) setSettings(found);
    });
    return () => {
      live = false;
    };
  }, [bridge]);
  if (settings === null) return null;
  const change = (patch: Partial<LinuxSettings>) => {
    setSettings({ ...settings, ...patch });
    void bridge.setSettings(patch).then(setSettings);
  };
  return (
    <SettingsSection title="Linux">
      <SettingsListRow
        title="Keep the pixie pill on top"
        detail="Runs Nest through XWayland, from the next start"
        trailing={
          <Toggle
            label="Keep the pixie pill on top"
            checked={settings.keepPillOnTop}
            onChange={(keepPillOnTop) => {
              change({ keepPillOnTop });
            }}
          />
        }
      />
      <SwitchRow
        label="Start Nest when I log in"
        on={settings.startAtLogin}
        onChange={(startAtLogin) => {
          change({ startAtLogin });
        }}
      />
    </SettingsSection>
  );
}

function VersionRow() {
  const { actions } = useStore();
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void actions.version().then((found) => {
      if (live) setVersion(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);
  return (
    <SettingsRow label="Version">
      <Value text={version ?? "-"} />
    </SettingsRow>
  );
}

/**
 * Restart Nest (B60): after a confirmation the Nest service restarts and the window loads
 * again once it answers; when it does not come back, the page says so.
 */
function RestartRow() {
  const { actions } = useStore();
  const [confirming, setConfirming] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [failed, setFailed] = useState(false);

  const restart = async () => {
    setRestarting(true);
    setFailed(false);
    const result = await actions.restartService();
    if (result === "back") {
      window.location.reload();
      return;
    }
    setRestarting(false);
    setFailed(result === "timeout");
  };

  return (
    <>
      <SettingsRow label="Restart Nest">
        {restarting && <Fireflies />}
        <Button
          disabled={restarting}
          onClick={() => {
            setConfirming(true);
          }}
        >
          Restart
        </Button>
      </SettingsRow>
      {failed && <Failure text="Nest did not come back." />}
      {confirming && (
        <Alert
          title="Restart Nest?"
          message="Running turns are interrupted and can be resumed afterwards."
          actions={[{ title: "Restart", onSelect: () => void restart() }]}
          onClose={() => {
            setConfirming(false);
          }}
        />
      )}
    </>
  );
}

/** The strip's update and button, here whether or not the strip was hidden. */
function UpdateRow() {
  const { state } = useStore();
  const relaunch = useRelaunch();
  const ready = readyUpdate(state.updates, "app");
  if (ready === null) return null;
  const question = relaunch.asking === null ? null : restartQuestion("relaunch", relaunch.asking);
  return (
    <>
      <SettingsRow label="Update available">
        <span className="dks-val lines">{updateChanges(ready)}</span>
        <Button disabled={ready.relaunching} onClick={() => void relaunch.start()}>
          {ready.relaunching ? "Relaunching..." : "Relaunch to update"}
        </Button>
      </SettingsRow>
      {question !== null && (
        <Alert
          title={question.title}
          message={question.about}
          actions={[{ title: question.action, onSelect: relaunch.confirm }]}
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
  const question = undo.asking === null ? null : restartQuestion("undo", undo.asking);
  return (
    <>
      <SettingsRow label="Undo update">
        {undoing && <Fireflies />}
        <Button disabled={undo.restarting !== null} onClick={() => void undo.start()}>
          Undo
        </Button>
      </SettingsRow>
      {question !== null && (
        <Alert
          title={question.title}
          message={question.about}
          actions={[{ title: question.action, onSelect: undo.confirm }]}
          onClose={undo.cancel}
        />
      )}
    </>
  );
}
