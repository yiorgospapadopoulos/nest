import { useRef, type PointerEvent } from "react";
import type { Session } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { ChatStatus } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

export const LONG_PRESS_MS = 520;
const MOVE_TOLERANCE = 8;
const SWIPE_DISTANCE = 56;

interface Props {
  session: Session;
  status: ChatStatus;
  onOpen: () => void;
  onActions: () => void;
}

/** A chat in the list: tap opens it; long-press, swipe left or the dots button show actions. */
export function ChatRow({ session, status, onOpen, onActions }: Props) {
  const press = useRef<{ x: number; y: number; timer: number; handled: boolean } | null>(null);
  // Set when a gesture opened the actions, so the click that follows does not open the chat.
  const swallowClick = useRef(false);

  const end = () => {
    const p = press.current;
    press.current = null;
    if (p !== null) window.clearTimeout(p.timer);
    return p;
  };

  const handlers = {
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return;
      const p = { x: event.clientX, y: event.clientY, timer: 0, handled: false };
      p.timer = window.setTimeout(() => {
        p.handled = true;
        onActions();
      }, LONG_PRESS_MS);
      press.current = p;
    },
    onPointerMove: (event: PointerEvent<HTMLButtonElement>) => {
      const p = press.current;
      if (p === null) return;
      const dx = event.clientX - p.x;
      if (Math.abs(dx) > MOVE_TOLERANCE || Math.abs(event.clientY - p.y) > MOVE_TOLERANCE) {
        window.clearTimeout(p.timer);
      }
      if (dx < -SWIPE_DISTANCE && !p.handled) {
        p.handled = true;
        onActions();
      }
    },
    onPointerUp: () => {
      swallowClick.current = end()?.handled === true;
    },
    onPointerCancel: () => {
      end();
    },
  };

  const label =
    `${session.title}, ${status.label}` +
    `${session.stuck !== null ? ", stuck" : ""}${session.pinned ? ", pinned" : ""}`;
  return (
    <div className="lrow">
      <button
        className="row"
        aria-label={label}
        onClick={() => {
          if (swallowClick.current) swallowClick.current = false;
          else onOpen();
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          end();
          onActions();
        }}
        {...handlers}
      >
        <Dot tone={status.tone} />
        <span className="rt">{session.title}</span>
        <span className="rm">
          {session.stuck !== null && (
            <span className="stk" title={session.stuck.details}>
              Stuck
            </span>
          )}
          {session.pinned && <Icon name="pin" />}
          {ago(session.updated_at, new Date())}
        </span>
        <Icon name="chevr" className="chv" />
      </button>
      <button className="rmore" aria-label={`Actions for ${session.title}`} onClick={onActions}>
        <Icon name="dots" />
      </button>
    </div>
  );
}
