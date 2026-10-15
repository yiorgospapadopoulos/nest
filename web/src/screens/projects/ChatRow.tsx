import type { Session } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { ChatStatus } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { useStore } from "../../store/context.ts";
import { placeLabel, sessionPlace } from "../chat/place.ts";
import { PlaceMark } from "../chat/PlaceMarks.tsx";
import { startedByText } from "../pixies/options.ts";
import { StartedBy } from "../pixies/StartedBy.tsx";
import { useRowGestures } from "./rowGestures.ts";

interface Props {
  session: Session;
  status: ChatStatus;
  onOpen: () => void;
  onActions: () => void;
}

/**
 * A chat in the list: its whole title, then where it works and its other marks beneath.
 * Tap opens it; long-press, swipe left or the dots button show actions.
 */
export function ChatRow({ session, status, onOpen, onActions }: Props) {
  const { state } = useStore();
  const gestures = useRowGestures(onOpen, onActions);
  const starter = session.started_by_pixie;
  const startedBy = starter === null ? "" : `, ${startedByText(state.pixies[starter]?.name)}`;
  const place = sessionPlace(
    session,
    state.repos.find((r) => r.name === session.repo),
  );
  const label =
    `${session.title}, ${status.label}${startedBy}` +
    `${session.stuck !== null ? ", stuck" : ""}${session.pinned ? ", pinned" : ""}` +
    placeLabel(place);
  return (
    <div className="lrow">
      <button className="row" aria-label={label} data-chat={session.id} {...gestures}>
        <Dot tone={status.tone} />
        <span className="rbody">
          <span className="rt">{session.title}</span>
          <span className="rsub">
            <PlaceMark place={place} />
            {starter !== null && <StartedBy id={starter} className="rby" />}
            {session.stuck !== null && (
              <span className="stk" title={session.stuck.details}>
                Stuck
              </span>
            )}
            {session.pinned && <Icon name="pin" />}
            <span className="ago">{ago(session.updated_at, new Date())}</span>
          </span>
        </span>
        <Icon name="chevr" className="chv" />
      </button>
      <button className="rmore" aria-label={`Actions for ${session.title}`} onClick={onActions}>
        <Icon name="dots" />
      </button>
    </div>
  );
}
