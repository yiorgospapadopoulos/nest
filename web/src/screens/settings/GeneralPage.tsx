import { useEffect, useState } from "react";
import { useStore } from "../../store/context.ts";
import { Confirm } from "../pixies/Confirm.tsx";
import { Row, Section } from "./rows.tsx";

type Phase = "idle" | "confirm" | "restarting" | "failed";

/** Nest itself: the version and Restart (B81). Storage has its own page (B86). */
export function GeneralPage() {
  return <NestSection />;
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
