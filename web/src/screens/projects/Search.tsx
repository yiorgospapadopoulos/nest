import { useEffect, useState } from "react";
import type { SearchHit, SearchResults } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { groupHits, type ChatHits } from "./searchHits.ts";

// Typing pauses this long before the Mac is asked.
const SEARCH_DELAY_MS = 250;

const KIND_LABELS: Record<SearchHit["kind"], string> = {
  title: "Title",
  user: "You",
  assistant: "Claude",
  tool: "Tool",
  tool_result: "Output",
  claude_chat: "Claude Code",
};

/** Text with the daemon's [[match]] markers shown highlighted. */
export function Snippet({ text }: { text: string }) {
  return (
    <>
      {text
        .split(/(\[\[[\s\S]*?\]\])/)
        .map((part, index) =>
          part.startsWith("[[") && part.endsWith("]]") ? (
            <mark key={index}>{part.slice(2, -2)}</mark>
          ) : (
            part
          ),
        )}
    </>
  );
}

interface FieldProps {
  query: string;
  onQuery: (query: string) => void;
}

export function SearchField({ query, onQuery }: FieldProps) {
  return (
    <div className="sfield gl" role="search">
      <Icon name="search" />
      <input
        type="search"
        aria-label="Search chats"
        placeholder="Search chats"
        enterKeyHint="search"
        value={query}
        onChange={(event) => {
          onQuery(event.target.value);
        }}
      />
      {query !== "" && (
        <button
          aria-label="Clear search"
          onClick={() => {
            onQuery("");
          }}
        >
          <Icon name="x" />
        </button>
      )}
    </div>
  );
}

interface Props {
  query: string;
  onOpenChat: (sessionId: string, event?: number) => void;
  onOpenClaudeChat: (chatId: string) => void;
}

/** Chats whose title or messages match, grouped by chat; a hit opens the chat at it. */
export function SearchResultsList({ query, onOpenChat, onOpenClaudeChat }: Props) {
  const { actions } = useStore();
  const wanted = query.trim();
  const [results, setResults] = useState<{ query: string; found: SearchResults | null }>({
    query: "",
    found: null,
  });

  useEffect(() => {
    let current = true;
    const timer = window.setTimeout(() => {
      void actions.search(wanted).then((found) => {
        if (current) setResults({ query: wanted, found });
      });
    }, SEARCH_DELAY_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [actions, wanted]);

  if (results.query !== wanted) return <p className="sempty">Searching…</p>;
  const found = results.found;
  if (found === null) return <p className="sempty">Search is not available right now.</p>;
  const groups = groupHits(found.hits);
  const open = (group: ChatHits, event: number | null) => {
    if (group.claude) onOpenClaudeChat(group.id);
    else if (event === null) onOpenChat(group.id);
    else onOpenChat(group.id, event);
  };

  return (
    <div className="sres" aria-label="Search results">
      {found.indexing && <p className="note">Still indexing older chats on your Mac.</p>}
      {groups.length === 0 && <p className="sempty">No chats match.</p>}
      {groups.map((group) => (
        <section key={group.id} className="lgrp gl" aria-label={group.title}>
          <button
            className="sres-h"
            onClick={() => {
              open(group, null);
            }}
          >
            <span className="rt">
              {group.titleHit === null ? group.title : <Snippet text={group.titleHit.snippet} />}
            </span>
            <span className="rm">{group.claude ? `${group.repo} · Claude Code` : group.repo}</span>
          </button>
          {group.hits.map((hit) => (
            <button
              key={`${String(hit.event_id)}-${hit.kind}`}
              className="sres-hit"
              onClick={() => {
                open(group, hit.event_id);
              }}
            >
              <span className="sk">{KIND_LABELS[hit.kind]}</span>
              <span className="sn">
                <Snippet text={hit.snippet} />
              </span>
            </button>
          ))}
        </section>
      ))}
    </div>
  );
}
