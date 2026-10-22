import { useEffect, useState } from "react";
import type { ListedDevice, PairingCode } from "../../api/types.ts";
import { clockTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { Section } from "./rows.tsx";

/** The paired devices, each but this one and the Mac with Revoke, and Pair a device. */
export function DevicesPage() {
  const { state, actions } = useStore();
  const [devices, setDevices] = useState<ListedDevice[] | null>(null);
  const [asking, setAsking] = useState<ListedDevice | null>(null);
  // Revoked here since the list loaded.
  const [revoked, setRevoked] = useState<string[]>([]);
  const [code, setCode] = useState<PairingCode | null>(null);

  useEffect(() => {
    let live = true;
    void actions.devices().then((found) => {
      if (live) setDevices(found ?? []);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const pair = async () => {
    const created = await actions.pairingCode();
    if (created !== null) setCode(created);
  };
  const shown = (devices ?? []).filter((d) => d.revoked_at === null && !revoked.includes(d.id));

  return (
    <>
      <Section>
        {devices === null && <div className="srow note">Loading...</div>}
        {shown.map((device) => (
          <div key={device.id} className="srow">
            <span className="cn">
              <span className="cico" aria-hidden="true">
                <Icon name="devices" />
              </span>
              <span className="slab">
                {device.name}
                {device.is_local && <span className="hint">{state.machine ?? "This Mac"}</span>}
                {device.this_device && <span className="hint">This device</span>}
              </span>
            </span>
            {!device.is_local && !device.this_device && (
              <button
                className="b b-no"
                aria-label={`Revoke ${device.name}`}
                onClick={() => {
                  setAsking(device);
                }}
              >
                Revoke
              </button>
            )}
          </div>
        ))}
        <div className="srow">
          <button className="b b-pri" onClick={() => void pair()}>
            Pair a device
          </button>
        </div>
      </Section>
      {asking !== null && (
        <Confirm
          title={`Revoke ${asking.name}?`}
          about="It must be paired again to use Nest."
          action="Revoke"
          onConfirm={() =>
            void actions.revokeDevice(asking).then((done) => {
              if (done) setRevoked((before) => [...before, asking.id]);
            })
          }
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
      {code !== null && (
        <Sheet
          title="Pair a device"
          onClose={() => {
            setCode(null);
          }}
        >
          <div className="pcode">
            <b aria-label="Pairing code">{code.code}</b>
            <span className="hint">Until {clockTime(new Date(code.expires_at))}</span>
          </div>
        </Sheet>
      )}
    </>
  );
}
