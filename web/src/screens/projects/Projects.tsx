import { Fragment, useState } from "react";
import type { ClaudeChat, Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import {
  chatLists,
  GROUP_LABELS,
  isRunning,
  needsCount,
  type ChatEntry,
} from "../../store/selectors.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { ChatActions } from "./ChatActions.tsx";
import { ChatRow } from "./ChatRow.tsx";
import { ChatTree, type WorkOf } from "./ChatTree.tsx";
import { ClaudeChatActions } from "./ClaudeChatActions.tsx";
import { ClaudeChatRow } from "./ClaudeChatRow.tsx";
import { GoalsSection } from "./GoalsSection.tsx";
import { SearchField, SearchResultsList } from "./Search.tsx";
import { PixieSection } from "../pixies/PixieSection.tsx";
import type { PixieTab } from "../pixies/PixieView.tsx";
import { Fireflies } from "../../ui/Fireflies.tsx";

interface Props {
  project: string | null;
  onProject: (name: string) => void;
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
 * A search over every chat, then project chips and the selected project's chats grouped
 * like the Mac sidebar. While a search is typed, its results replace the lists.
 */
export function Projects({
  project,
  onProject,
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
  const lists = project === null ? null : chatLists(state, project);
  const empty = lists !== null && lists.groups.length === 0 && lists.archived.length === 0;

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

  const listsView = (
    <>
      <PixieSection project={project} onOpen={onOpenPixie} />
      {state.repos.length === 0 && (
        <p className="sempty">No projects yet. Add one in the Nest app on your Mac.</p>
      )}
      <div className="pchips" role="tablist" aria-label="Projects">
        {state.repos.map((repo) => {
          const on = repo.name === project;
          const needs = needsCount(state, repo.name);
          return (
            <button
              key={repo.name}
              className={`pchip${on ? " on" : ""}${!on && needs > 0 ? " attn" : ""}`}
              role="tab"
              aria-selected={on}
              onClick={() => {
                onProject(repo.name);
              }}
            >
              <ProjectIcon name={repo.name} />
              <span>{repo.name}</span>
              {needs > 0 ? (
                <span className="pbadge" aria-label={`${String(needs)} need you`}>
                  {needs}
                </span>
              ) : (
                isRunning(state, repo.name) && <Fireflies size={9} label="running" />
              )}
            </button>
          );
        })}
      </div>
      {project !== null && <GoalsSection project={project} onOpenChat={onOpenChat} />}
      {empty && <div className="sempty">No chats yet</div>}
      {lists?.groups.map(({ group, chats }) => (
        <section key={group} aria-labelledby={`group-${group}`}>
          <h2 className="pg-h" id={`group-${group}`}>
            {group === "pinned" && <Icon name="pin" />}
            {GROUP_LABELS[group]}
            <span className="gc">{chats.length}</span>
          </h2>
          <div className="lgrp gl">{chats.map(row)}</div>
        </section>
      ))}
      {lists !== null && lists.archived.length > 0 && (
        <>
          <button
            className="pg-h pgb"
            aria-expanded={showArchived}
            onClick={() => {
              setShowArchived(!showArchived);
            }}
          >
            <Icon name="chev" className="cv" />
            Archived
            <span className="gc">{lists.archived.length}</span>
          </button>
          {showArchived && <div className="lgrp gl">{lists.archived.map(row)}</div>}
        </>
      )}
      {project !== null && (
        <div className="srow gl pauto">
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
      )}
    </>
  );

  return (
    <>
      <div className="navr">
        {project !== null && (
          <>
            <button
              className="ib gl"
              aria-label={`Settings for ${project}`}
              onClick={() => {
                onOpenSettings(project);
              }}
            >
              <Icon name="gear" />
            </button>
            <button
              className="ib gl"
              aria-label={`New chat in ${project}`}
              onClick={() => {
                onNewChat(project);
              }}
            >
              <Icon name="plus" />
            </button>
          </>
        )}
      </div>
      <h1 className="lt">Projects</h1>
      <SearchField query={query} onQuery={setQuery} />
      {query.trim() !== "" ? (
        <SearchResultsList
          query={query}
          onOpenChat={onOpenChat}
          onOpenClaudeChat={onOpenClaudeChat}
          onOpenPixie={(id) => {
            onOpenPixie(id, "chat");
          }}
        />
      ) : (
        listsView
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
