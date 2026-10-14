import { useStore } from "../../store/context.ts";
import { startedByText } from "./options.ts";
import { Sprite } from "./Sprite.tsx";

/** "Started by Tester" with its mascot, for a chat a pixie started (B41). */
export function StartedBy({ id, className }: { id: string; className: string }) {
  const { state } = useStore();
  const pixie = state.pixies[id];
  return (
    <span className={`pxby ${className}`}>
      {pixie !== undefined && (
        <span aria-hidden="true">
          <Sprite mascot={pixie.mascot} color={pixie.color} size={14} />
        </span>
      )}
      <span>{startedByText(pixie?.name)}</span>
    </span>
  );
}
