import type { ClaudeChat } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  chat: ClaudeChat;
  onClose: () => void;
}

/** Archive or unarchive a Claude Code chat; Nest keeps that state, Claude Code never sees it. */
export function ClaudeChatActions({ chat, onClose }: Props) {
  const { actions } = useStore();
  const archive = async () => {
    if (await actions.archiveClaudeChat(chat, !chat.archived)) onClose();
  };
  return (
    <ActionSheet label={`Actions for ${chat.title}`} title={<b>{chat.title}</b>} onClose={onClose}>
      <button className="asi" role="menuitem" onClick={() => void archive()}>
        <Icon name="archive" />
        <span>{chat.archived ? "Unarchive" : "Archive"}</span>
      </button>
    </ActionSheet>
  );
}
