import { Icon } from "../../ui/Icon.tsx";
import type { Stopper } from "./useStopTask.ts";

/** A small stop square on a running task's row; it never opens or closes the row. */
export function StopTask({
  id,
  name,
  stopper,
}: {
  id: string;
  name: string;
  stopper: Stopper | null;
}) {
  if (!stopper?.offered(id)) return null;
  return (
    <button
      className="tstop"
      aria-label={`Stop ${name}`}
      disabled={stopper.stopping(id)}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        stopper.stop(id);
      }}
    >
      <Icon name="stop" />
    </button>
  );
}
