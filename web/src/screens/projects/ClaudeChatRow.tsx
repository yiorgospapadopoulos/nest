import type { ClaudeChat } from "../../api/types.ts";
import { ago } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { claudeChatPlace, placeLabel } from "../chat/place.ts";
import { PlaceMark } from "../chat/PlaceMarks.tsx";
import { useRowGestures } from "./rowGestures.ts";

interface Props {
  chat: ClaudeChat;
  onOpen: () => void;
  onActions: () => void;
}

/**
 * A Claude Code chat in the list, marked like a Nest chat by where it works (B55);
 * tap opens its history, gestures its actions.
 */
export function ClaudeChatRow({ chat, onOpen, onActions }: Props) {
  const { state } = useStore();
  const gestures = useRowGestures(onOpen, onActions);
  const open = chat.open_in_claude_code ? ", open in Claude Code" : "";
  const place = claudeChatPlace(
    chat,
    state.repos.find((r) => r.name === chat.repo),
  );
  return (
    <div className="lrow">
      <button
        className="row"
        aria-label={`${chat.title}, Claude Code chat${open}${placeLabel(place)}`}
        data-chat={chat.id}
        {...gestures}
      >
        <Dot tone={chat.open_in_claude_code ? "run" : "idle"} />
        <span className="rbody">
          <span className="rt">{chat.title}</span>
          <span className="rsub">
            <PlaceMark place={place} />
            <span className="ago">{ago(chat.last_activity_at, new Date())}</span>
          </span>
        </span>
        <Icon name="chevr" className="chv" />
      </button>
      <button className="rmore" aria-label={`Actions for ${chat.title}`} onClick={onActions}>
        <Icon name="dots" />
      </button>
    </div>
  );
}
