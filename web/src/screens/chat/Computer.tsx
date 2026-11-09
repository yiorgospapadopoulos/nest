// Computer use on the phone (B150): the live strip on the composer, which grows upward
// when tapped, and its approval cards.
import { useState } from "react";
import type { ComputerAsk } from "../../api/payloads.ts";
import type { Approval, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { useComputerAsk } from "../approvals/hooks.ts";
import { useFrame, useHeld, useWaiting } from "./useComputer.ts";

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
  const shot = url !== null && <img src={url} alt={name} />;
  const toggle = () => {
    setLarge(!large);
  };
  const controls = (
    <>
      <span className="cu-app">{name}</span>
      <Dot tone={waiting ? "wait" : "run"} plain />
      <span className="flex" />
      <button className="cu-ico" aria-label={large ? "Shrink" : "Enlarge"} onClick={toggle}>
        <Icon name={large ? "shrink" : "expand"} />
      </button>
      <button
        className="cu-stop"
        disabled={stopping}
        onClick={() => {
          setStopping(true);
          void actions.stopComputerUse(session.id).then(() => {
            setStopping(false);
          });
        }}
      >
        <Icon name="stop" />
        Stop
      </button>
    </>
  );
  return (
    <div className={large ? "cu large" : "cu"} role="group" aria-label={`Using ${name}`}>
      {large ? (
        <>
          <div className="cu-hd">{controls}</div>
          {shot !== false && (
            <button className="cu-shot" tabIndex={-1} aria-hidden="true" onClick={toggle}>
              {shot}
            </button>
          )}
        </>
      ) : (
        <>
          <button className="cu-shot" tabIndex={-1} aria-hidden="true" onClick={toggle}>
            {shot}
          </button>
          {controls}
        </>
      )}
    </div>
  );
}

/** A computer use card in the transcript: the question, a screenshot to act on, answers. */
export function ComputerAskCard({ approval, ask }: { approval: Approval; ask: ComputerAsk }) {
  return (
    <div className="ask" role="group" aria-label="Needs approval">
      <div className="ask-h">
        <Dot tone="wait" />
        <span>Needs approval</span>
      </div>
      <ComputerAskBody approval={approval} ask={ask} />
    </div>
  );
}

/** The card's question, reason, screenshot and answers, as the inbox opens them too. */
export function ComputerAskBody({ approval, ask }: { approval: Approval; ask: ComputerAsk }) {
  const { busy, decide } = useComputerAsk(approval);
  return (
    <>
      <p className="cu-q">{ask.question}</p>
      {ask.reason !== null && <div className="why">{ask.reason}</div>}
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void decide("allow")}>
          Allow
        </button>
        <button className="b" disabled={busy} onClick={() => void decide("deny")}>
          Deny
        </button>
      </div>
    </>
  );
}
