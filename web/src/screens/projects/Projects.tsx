import { Fragment, useState } from "react";
import type { ClaudeChat, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { chatList, type ChatEntry } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ChatActions } from "./ChatActions.tsx";
import { ChatRow } from "./ChatRow.tsx";
import { ChatTree, type WorkOf } from "./ChatTree.tsx";
import { ClaudeChatActions } from "./ClaudeChatActions.tsx";
import { ClaudeChatRow } from "./ClaudeChatRow.tsx";
import { ProjectHeader } from "./ProjectHeader.tsx";
import { SearchField, SearchResultsList } from "./Search.tsx";
import { PixieSection } from "../pixies/PixieSection.tsx";
import type { PixieTab } from "../pixies/PixieView.tsx";

interface Props {
  project: string | null;
  // The pixies show instead of a project, as the Mac's Pixies tab (B102).
  pixies: boolean;
  onProject: (name: string) => void;
  onPixies: () => void;
  // `event`: scroll to it, as for a search hit.
  onOpenChat: (sessionId: string, event?: number) => void;
  onOpenClaudeChat: (chatId: string) => void;
  onNewChat: (repo: string) => void;
  onOpenPixie: (id: string, tab: PixieTab) => void;
  // A subagent's transcript, or a pixie's or team's work, in a chat (B46).
  onOpenAgent: (sessionId: string, toolUseId: string) => void;
  onOpenWork: (sessionId: string, who: WorkOf) => void;
  // The project's page in Settings (B81).
  onOpenSettings: (repo: string) => void;
}

/**
 * The Chats tab, as the Mac sidebar: a header with the project and its menu, a search over
 * every chat, then the project's chats in one list by their latest message (B102), or the
 * pixies. While a search is typed, its results replace the list.
 */
export function Projects({
  project,
  pixies,
  onProject,
  onPixies,
  onOpenChat,
  onOpenClaudeChat,
  onNewChat,
  onOpenPixie,
  onOpenAgent,
  onOpenWork,
  onOpenSettings,
}: Props) {
  const { state, actions } = useStore();
  const [showArchived, setShowArchived] = useState(false);
  const [acting, setActing] = useState<Session | null>(null);
  const [actingChat, setActingChat] = useState<ClaudeChat | null>(null);
  const [query, setQuery] = useState("");
  const repo = state.repos.find((r) => r.name === project) ?? null;

  const newPixie = async () => {
    const created = await actions.createPixie({ name: "New pixie" });
    if (created !== null) onOpenPixie(created.id, "details");
  };

  const row = ({ session, chat, status }: ChatEntry) =>
    session === undefined ? (
      <ClaudeChatRow
        key={`cc-${chat.id}`}
        chat={chat}
        onOpen={() => {
          onOpenClaudeChat(chat.id);
        }}
        onActions={() => {
          setActingChat(chat);
        }}
      />
    ) : (
      <Fragment key={session.id}>
        <ChatRow
          session={session}
          status={status}
          onOpen={() => {
            onOpenChat(session.id);
          }}
          onActions={() => {
            setActing(session);
          }}
        />
        <ChatTree
          session={session}
          onOpenAgent={(call) => {
            onOpenAgent(session.id, call);
          }}
          onOpenWork={(who) => {
            onOpenWork(session.id, who);
          }}
        />
      </Fragment>
    );

  const section = (id: string, label: string, entries: ChatEntry[]) =>
    entries.length > 0 && (
      <section aria-labelledby={id}>
        <h2 className="lbl" id={id}>
          {label}
          <span className="c">{entries.length}</span>
        </h2>
        <div className="lgrp">{entries.map(row)}</div>
      </section>
    );

  const chatsView = (name: string) => {
    const lists = chatList(state, name);
    const empty = lists.pinned.length + lists.chats.length + lists.archived.length === 0;
    return (
      <>
        {empty && <div className="sempty">No chats yet</div>}
        {section("chats-pinned", "Pinned", lists.pinned)}
        {section("chats-all", "Chats", lists.chats)}
        {lists.archived.length > 0 && (
          <>
            <button
              className="lbl folded"
              aria-expanded={showArchived}
              onClick={() => {
                setShowArchived(!showArchived);
              }}
            >
              <Icon name="chev" className="cv" />
              Archived
              <span className="c">{lists.archived.length}</span>
            </button>
            {showArchived && <div className="lgrp">{lists.archived.map(row)}</div>}
          </>
        )}
        <div className="srow pauto">
          <span id="show-automated">Show automated chats</span>
          <button
            className="sw"
            role="switch"
            aria-checked={state.showAutomated}
            aria-labelledby="show-automated"
            onClick={() => {
              void actions.setShowAutomated(!state.showAutomated);
            }}
          />
        </div>
      </>
    );
  };

  const listView = pixies ? (
    <PixieSection onOpen={onOpenPixie} />
  ) : repo === null ? (
    <p className="sempty">No projects yet. Add one in the Nest app on your Mac.</p>
  ) : (
    chatsView(repo.name)
  );

  return (
    <>
      <ProjectHeader
        repo={repo}
        pixies={pixies}
        onProject={onProject}
        onPixies={onPixies}
        onAdd={
          pixies
            ? () => void newPixie()
            : repo === null
              ? null
              : () => {
                  onNewChat(repo.name);
                }
        }
        onSettings={onOpenSettings}
      />
      {/* The Mac's Pixies tab has no search over chats. */}
      {!pixies && <SearchField query={query} onQuery={setQuery} />}
      {!pixies && query.trim() !== "" ? (
        <SearchResultsList
          query={query}
          onOpenChat={onOpenChat}
          onOpenClaudeChat={onOpenClaudeChat}
          onOpenPixie={(id) => {
            onOpenPixie(id, "chat");
          }}
        />
      ) : (
        listView
      )}
      {acting !== null && (
        <ChatActions
          session={acting}
          onClose={() => {
            setActing(null);
          }}
        />
      )}
      {actingChat !== null && (
        <ClaudeChatActions
          chat={actingChat}
          onClose={() => {
            setActingChat(null);
          }}
        />
      )}
    </>
  );
}
