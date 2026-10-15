import { useState } from "react";
import { useStore } from "../../store/context.ts";
import { Confirm } from "../pixies/Confirm.tsx";

type Phase = "idle" | "confirm" | "restarting" | "failed";

/** Restarts the daemon on the Mac, then loads the page again once it answers. */
export function RestartCard() {
  const { actions } = useStore();
  const [phase, setPhase] = useState<Phase>("idle");
  const restarting = phase === "restarting";

  const restart = async () => {
    setPhase("restarting");
    const result = await actions.restartService();
    if (result === "back") window.location.reload();
    else setPhase(result === null ? "idle" : "failed");
  };

  return (
    <section aria-labelledby="restart-title">
      <h2 className="pg-h" id="restart-title">
        Restart Nest
      </h2>
      <div className="lgrp gl">
        <div className="srow col">
          <span className="hint">
            Restarts Nest on your Mac. Running turns are interrupted and can be resumed.
          </span>
          <button
            className="b"
            disabled={restarting}
            onClick={() => {
              setPhase("confirm");
            }}
          >
            {restarting ? "Restarting..." : "Restart Nest"}
          </button>
        </div>
        {phase === "failed" && (
          <p className="pad note" role="alert">
            Nest did not come back. Check that the Mac is awake, then reload.
          </p>
        )}
      </div>
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
    </section>
  );
}
