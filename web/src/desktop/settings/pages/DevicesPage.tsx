import { useEffect, useState } from "react";
import type { ListedDevice, PairingCode } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { useApi } from "../../context.ts";
import { reachable, tailscaleStage } from "../../setup/steps.ts";
import { useShell } from "../../shell/context.ts";
import { Button } from "../../ui/controls.tsx";
import { Alert } from "../../sheets/Alert.tsx";
import {
  THIS_COMPUTER,
  canRevoke,
  deviceDetail,
  deviceTitle,
  shownDevices,
} from "../parts3/devices.ts";
import { PairingCodeView } from "../parts3/PairingCodeView.tsx";
import { Note, SettingsListRow, SettingsSection } from "../rows.tsx";
import "../parts3/parts3.css";

/**
 * The devices paired with this computer's daemon, with Revoke, and pairing a new one with a
 * one-time code, as the Mac's DevicesPage. The Mac's Daemons section is left out: the
 * desktop app talks only to the daemon on this computer.
 */
export function DevicesPage() {
  const { actions } = useStore();
  const api = useApi();
  const shell = useShell();
  const [devices, setDevices] = useState<ListedDevice[] | null>(null);
  const [asking, setAsking] = useState<ListedDevice | null>(null);
  const [revoking, setRevoking] = useState<string[]>([]);
  const [code, setCode] = useState<PairingCode | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let live = true;
    void actions.devices().then((found) => {
      if (live && found !== null) setDevices(shownDevices(found));
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const createCode = async () => {
    setCreating(true);
    const created = await actions.pairingCode();
    setCreating(false);
    if (created !== null) setCode(created);
  };

  // A code is no use before the phone can reach Nest: until Nest is shared on Tailscale,
  // the guide's Tailscale step opens instead. Checks that cannot run leave pairing as it was.
  const pair = async () => {
    setCreating(true);
    const checks = await api.setupChecks().catch(() => null);
    const tailscale = checks?.checks.find((check) => check.id === "tailscale");
    if (tailscale !== undefined && !reachable(tailscaleStage(tailscale))) {
      setCreating(false);
      shell.openGuide("tailscale");
      return;
    }
    await createCode();
  };

  const revoke = async (device: ListedDevice) => {
    setAsking(null);
    setRevoking((ids) => [...ids, device.id]);
    const done = await actions.revokeDevice(device);
    setRevoking((ids) => ids.filter((id) => id !== device.id));
    if (done) setDevices((list) => list?.filter((d) => d.id !== device.id) ?? null);
  };

  return (
    <SettingsSection title={`Paired with ${THIS_COMPUTER}`} bare>
      <div className="dks3-list">
        {devices === null && <Note>Loading</Note>}
        {devices?.map((device) => (
          <SettingsListRow
            key={device.id}
            title={deviceTitle(device)}
            detail={deviceDetail(device, new Date())}
            leading={<DeviceBadge local={device.is_local} />}
            trailing={
              canRevoke(device) ? (
                <Button
                  kind="danger"
                  aria-label={`Revoke ${deviceTitle(device)}`}
                  disabled={revoking.includes(device.id)}
                  onClick={() => {
                    setAsking(device);
                  }}
                >
                  Revoke
                </Button>
              ) : undefined
            }
          />
        ))}
      </div>
      {code !== null ? (
        <PairingCodeView
          code={code}
          hint="Open your tailnet address in Safari on the iPhone, then enter this code."
          onNewCode={() => void createCode()}
          onDone={() => {
            setCode(null);
          }}
        />
      ) : (
        <div className="dks3-after wide">
          <Button kind="primary" disabled={creating} onClick={() => void pair()}>
            <Icon name="plus" />
            Pair a device
          </Button>
          {creating && <Fireflies />}
        </div>
      )}
      {asking !== null && (
        <Alert
          title={`Revoke ${deviceTitle(asking)}?`}
          message="It stops working at once and has to be paired again."
          actions={[{ title: "Revoke", kind: "destructive", onSelect: () => void revoke(asking) }]}
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
    </SettingsSection>
  );
}

/** A laptop for this computer's device, a phone for the others, as SettingsBadge. */
function DeviceBadge({ local }: { local: boolean }) {
  return (
    <span className="dks-badge" aria-hidden="true">
      <svg viewBox="0 0 16 16">
        {local ? (
          <path d="M3.5 4h9a.5.5 0 0 1 .5.5V10H3V4.5a.5.5 0 0 1 .5-.5ZM1.5 11.5h13" />
        ) : (
          <>
            <rect x="5" y="2" width="6" height="12" rx="1.2" />
            <path d="M7.3 12h1.4" />
          </>
        )}
      </svg>
    </span>
  );
}
