import type { Session } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { ChatStatus } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { useStore } from "../../store/context.ts";
import { startedByText } from "../pixies/options.ts";
import { StartedBy } from "../pixies/StartedBy.tsx";
import { useRowGestures } from "./rowGestures.ts";

interface Props {
  session: Session;
  status: ChatStatus;
  onOpen: () => void;
  onActions: () => void;
}

/** A chat in the list: tap opens it; long-press, swipe left or the dots button show actions. */
export function ChatRow({ session, status, onOpen, onActions }: Props) {
  const { state } = useStore();
  const gestures = useRowGestures(onOpen, onActions);
  const starter = session.started_by_pixie;
  const startedBy = starter === null ? "" : `, ${startedByText(state.pixies[starter]?.name)}`;
  const label =
    `${session.title}, ${status.label}${startedBy}` +
    `${session.stuck !== null ? ", stuck" : ""}${session.pinned ? ", pinned" : ""}`;
  return (
    <div className="lrow">
      <button className="row" aria-label={label} data-chat={session.id} {...gestures}>
        <Dot tone={status.tone} />
        <span className="rt">{session.title}</span>
        {starter !== null && <StartedBy id={starter} className="rby" />}
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
