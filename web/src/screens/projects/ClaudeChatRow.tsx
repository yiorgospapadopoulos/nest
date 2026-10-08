import type { ClaudeChat } from "../../api/types.ts";
import { ago } from "../../format.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { useRowGestures } from "./rowGestures.ts";

interface Props {
  chat: ClaudeChat;
  onOpen: () => void;
  onActions: () => void;
}

/** A Claude Code chat in the list, marked as such; tap opens its history, gestures its actions. */
export function ClaudeChatRow({ chat, onOpen, onActions }: Props) {
  const gestures = useRowGestures(onOpen, onActions);
  const open = chat.open_in_claude_code ? ", open in Claude Code" : "";
  return (
    <div className="lrow">
      <button
        className="row"
        aria-label={`${chat.title}, Claude Code chat${open}`}
        data-chat={chat.id}
        {...gestures}
      >
        <Dot tone={chat.open_in_claude_code ? "run" : "idle"} />
        <span className="rt">{chat.title}</span>
        <span className="rm">
          <span className="ccm" title="From Claude Code">
            <Icon name="term" />
            Claude Code
          </span>
          {ago(chat.last_activity_at, new Date())}
        </span>
        <Icon name="chevr" className="chv" />
      </button>
      <button className="rmore" aria-label={`Actions for ${chat.title}`} onClick={onActions}>
        <Icon name="dots" />
      </button>
    </div>
  );
}
