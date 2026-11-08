// Computer use on a pane (B150): the live strip on the composer while the chat holds an
// app, and the body of its approval cards.
import { useState } from "react";
import type { ComputerAsk } from "../../api/payloads.ts";
import type { Approval, Session } from "../../api/types.ts";
import { useComputerAsk } from "../../screens/approvals/hooks.ts";
import { useFrame, useHeld, useWaiting } from "../../screens/chat/useComputer.ts";
import { useStore } from "../../store/context.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Button } from "../ui/controls.tsx";
import { Glyph } from "./glyphs.tsx";
import { ImageSheet } from "./ImageSheet.tsx";

/** The live strip over the field while the chat holds an app; nothing otherwise. */
export function ComputerStrip({ session }: { session: Session }) {
  const held = useHeld(session.id);
  if (held.length === 0) return null;
  return <LiveStrip session={session} name={held.map((t) => t.name).join(", ")} />;
}

function LiveStrip({ session, name }: { session: Session; name: string }) {
  const { actions } = useStore();
  const url = useFrame(session.id);
  const waiting = useWaiting(session.id);
  const [large, setLarge] = useState(false);
  const [stopping, setStopping] = useState(false);
  const enlarge = () => {
    setLarge(true);
  };
  return (
    <div className="dc-cu" role="group" aria-label={`Using ${name}`}>
      {/* The same as Enlarge beside it, which assistive technology reaches instead. */}
      <button
        className="dc-cu-shot"
        tabIndex={-1}
        aria-hidden="true"
        disabled={url === null}
        onClick={enlarge}
      >
        {url !== null && <img src={url} alt="" />}
      </button>
      <span className="dc-cu-app">{name}</span>
      <span className={waiting ? "dc-dot" : "dc-dot run"} aria-hidden="true" />
      <span className="grow" />
      <Button
        kind="plain"
        iconOnly
        title="Enlarge"
        aria-label="Enlarge"
        disabled={url === null}
        onClick={enlarge}
      >
        <Glyph name="maximize" size={12} />
      </Button>
      <Button
        className="dc-cu-stop"
        disabled={stopping}
        onClick={() => {
          setStopping(true);
          void actions.stopComputerUse(session.id).then(() => {
            setStopping(false);
          });
        }}
      >
        <Glyph name="stop" size={11} />
        Stop
      </Button>
      {large && url !== null && (
        <ImageSheet
          url={url}
          alt={name}
          onClose={() => {
            setLarge(false);
          }}
        />
      )}
    </div>
  );
}

/** A computer use card: the question, the screenshot before an ask-first action, and answers. */
export function ComputerAskBody({ approval, ask }: { approval: Approval; ask: ComputerAsk }) {
  const { busy, decide } = useComputerAsk(approval);
  return (
    <>
      <p className="dc-ask-t strong">{ask.question}</p>
      {ask.reason !== null && <p className="dc-ask-why">{ask.reason}</p>}
      {ask.kind === "act" && <AskShot sessionId={approval.session_id} name={ask.name} />}
      <div className="dc-ask-acts">
        <Button kind="primary" disabled={busy} onClick={() => void decide("allow")}>
          Allow
        </Button>
        <Button disabled={busy} onClick={() => void decide("deny")}>
          Deny
        </Button>
        {busy && <Fireflies size={9} />}
      </div>
    </>
  );
}

function AskShot({ sessionId, name }: { sessionId: string; name: string }) {
  const url = useFrame(sessionId);
  if (url === null) return null;
  return <img className="dc-cu-ask" src={url} alt={name} />;
}
