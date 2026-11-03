import { useEffect, useState } from "react";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import type { LinuxSettings } from "../../bridge.ts";
import { useBridge } from "../../context.ts";
import { Button, Toggle } from "../../ui/controls.tsx";
import { Alert } from "../../sheets/Alert.tsx";
import {
  Failure,
  SettingsListRow,
  SettingsRow,
  SettingsSection,
  SwitchRow,
  Value,
} from "../rows.tsx";

/** The Mac's General (GeneralPages.swift): the sidebar's switch, this computer's, then Nest. */
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
      </SettingsSection>
    </>
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
