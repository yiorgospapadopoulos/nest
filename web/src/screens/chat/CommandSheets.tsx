import { useEffect, useState } from "react";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { ConnectorGroups } from "../account/ConnectorsCard.tsx";
import { SearchField, SearchResultsList } from "../projects/Search.tsx";

/** Where a chat can go from `/resume`, as the tabs open chats (B59). */
export interface ChatNav {
  openChat: (sessionId: string, event?: number) => void;
  openClaudeChat: (chatId: string) => void;
  openPixie: (id: string) => void;
}

/** `/mcp`: the MCP servers and connectors, with how to sign in to those that need it. */
export function ConnectorsSheet({ onClose }: { onClose: () => void }) {
  const { actions } = useStore();
  useEffect(() => {
    void actions.loadConnectors();
  }, [actions]);
  return (
    <Sheet title="Connectors" full onClose={onClose}>
      <ConnectorGroups opened />
    </Sheet>
  );
}

interface ResumeProps {
  repo: string;
  // The chat the command was typed in, left out of the list.
  current: string | undefined;
  // What followed `/resume`, searched for at once.
  query: string;
  nav: ChatNav;
  onClose: () => void;
}

/**
 * `/resume`: the project's other chats, latest first, or a search over every chat as in the
 * Projects tab. Choosing one opens it.
 */
export function ResumeSheet({ repo, current, query: initial, nav, onClose }: ResumeProps) {
  const { state } = useStore();
  const [query, setQuery] = useState(initial);
  const chats = Object.values(state.sessions)
    .filter(
      (s) => s.repo === repo && s.id !== current && s.archived_at === null && s.pixie_id == null,
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  // Each opens over this chat, so the sheet goes first.
  const go =
    <A extends unknown[]>(open: (...args: A) => void) =>
    (...args: A) => {
      onClose();
      open(...args);
    };
  return (
    <Sheet title="Resume a chat" full onClose={onClose}>
      <SearchField query={query} onQuery={setQuery} />
      {query.trim() === "" ? (
        chats.length === 0 ? (
          <p className="sempty">{`No other chats in ${repo}.`}</p>
        ) : (
          <div className="lgrp gl">
            {chats.map((chat) => (
              <button
                key={chat.id}
                className="sres-h"
                onClick={() => {
                  go(nav.openChat)(chat.id);
                }}
              >
                <span className="rt">{chat.title}</span>
              </button>
            ))}
          </div>
        )
      ) : (
        <SearchResultsList
          query={query}
          onOpenChat={go(nav.openChat)}
          onOpenClaudeChat={go(nav.openClaudeChat)}
          onOpenPixie={go(nav.openPixie)}
        />
      )}
    </Sheet>
  );
}
