import { useEffect, useState } from "react";
import type { PairingCode } from "../../../api/types.ts";
import { Button } from "../../ui/controls.tsx";
import { expiryText, secondsLeft } from "./devices.ts";
import "./parts3.css";

/** The one-time code, large, with its countdown; Settings adds where to enter it and Done. */
export function PairingCodeView({
  code,
  hint,
  className,
  onNewCode,
  onDone,
}: {
  code: PairingCode;
  hint?: string;
  className?: string;
  onNewCode: () => void;
  onDone?: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, []);
  const left = secondsLeft(code.expires_at, now);
  return (
    <div className={className === undefined ? "dks3-code" : `dks3-code ${className}`}>
      <b aria-label="Pairing code">{code.code}</b>
      <p className={left > 0 ? undefined : "gone"}>{expiryText(code.expires_at, now)}</p>
      {hint !== undefined && <p>{hint}</p>}
      <div className="dks3-buttons">
        <Button kind={onDone === undefined ? "soft" : "plain"} onClick={onNewCode}>
          New code
        </Button>
        {onDone !== undefined && <Button onClick={onDone}>Done</Button>}
      </div>
    </div>
  );
}
