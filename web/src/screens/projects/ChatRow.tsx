import type { Session } from "../../api/types.ts";
import { ago } from "../../format.ts";
import type { ChatStatus } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { useStore } from "../../store/context.ts";
import { repoNamed } from "../../store/general.ts";
import { earlierOf } from "../chat/earlier.ts";
import { EarlierList, EarlierToggle } from "../chat/EarlierWorktrees.tsx";
import { placeLabel, sessionPlace } from "../chat/place.ts";
import { PlaceMark } from "../chat/PlaceMarks.tsx";
import { startedByText } from "../pixies/options.ts";
import { StartedBy } from "../pixies/StartedBy.tsx";
import { useEarlierOpen } from "./earlierFold.ts";
import { useRowGestures } from "./rowGestures.ts";

interface Props {
  session: Session;
  status: ChatStatus;
  onOpen: () => void;
  onActions: () => void;
}

/**
 * A chat in the list: its whole title and the time since its latest message, then where
 * it works and its other marks beneath. Tap opens it; long-press, swipe left or the dots
 * button (shown to VoiceOver and the keyboard) show actions.
 */
export function ChatRow({ session, status, onOpen, onActions }: Props) {
  const { state } = useStore();
  const gestures = useRowGestures(onOpen, onActions);
  const [earlierOpen, toggleEarlier] = useEarlierOpen(session.id);
  const earlier = earlierOf(session);
  const starter = session.started_by_pixie;
  const startedBy = starter === null ? "" : `, ${startedByText(state.pixies[starter]?.name)}`;
  const place = sessionPlace(session, repoNamed(state.repos, session.repo));
  const label =
    `${session.title}, ${status.label}${startedBy}` +
    `${session.stuck !== null ? ", stuck" : ""}${session.pinned ? ", pinned" : ""}` +
    placeLabel(place) +
    (session.issue === null ? "" : `, issue #${String(session.issue.number)}`);
  const row = (
    <div className="lrow">
      <button className="row" aria-label={label} data-chat={session.id} {...gestures}>
        <Dot tone={status.tone} />
        <span className="rbody">
          <span className="rt">{session.title}</span>
          <span className="rsub">
            <PlaceMark place={place} />
            {session.issue !== null && <span className="rissue">#{session.issue.number}</span>}
            {starter !== null && <StartedBy id={starter} className="rby" />}
            {session.stuck !== null && (
              <span className="rstuck" title={session.stuck.details}>
                Stuck
              </span>
            )}
            {session.pinned && <Icon name="pin" />}
          </span>
        </span>
        <span className="rtime">{ago(session.updated_at, new Date())}</span>
      </button>
      <button className="rmore" aria-label={`Actions for ${session.title}`} onClick={onActions}>
        <Icon name="dots" />
      </button>
      {earlier.length > 0 && (
        <EarlierToggle
          title={session.title}
          count={earlier.length}
          open={earlierOpen}
          onToggle={toggleEarlier}
        />
      )}
    </div>
  );
  return earlier.length > 0 && earlierOpen ? (
    <>
      {row}
      <EarlierList worktrees={earlier} />
    </>
  ) : (
    row
  );
}
