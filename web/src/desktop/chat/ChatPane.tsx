// What a workspace pane shows for a chat, as the Mac's PaneView: the header, then the
// transcript with the bars over its bottom and the composer, the body faded while another
// pane has the focus (B93) and the header kept as it is. A Claude Code chat shows its
// history with Continue in Nest in place of the composer; a subagent's or pixie's work
// shows read-only.
import { useEffect, useState, type ReactNode } from "react";
import type { Session } from "../../api/types.ts";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { outsideEngineName } from "../../store/selectors.ts";
import { NO_BACKGROUND } from "../../store/state.ts";
import { Dot } from "../../ui/bits.tsx";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { useShell } from "../shell/context.ts";
import { claudePane } from "../shell/panes.ts";
import { Button } from "../ui/controls.tsx";
import { AutopilotBar, BackgroundBar, LimitBar, ReviewBar } from "./Bars.tsx";
import { Composer } from "./Composer.tsx";
import { FileLinks } from "./FileLinks.tsx";
import { Glyph } from "./glyphs.tsx";
import { ChatHeaderParts, HeaderFrame, HeaderTitle } from "./PaneHeader.tsx";
import type { NewChatChoice } from "./placePicker.ts";
import { RunControlView } from "./RunControl.tsx";
import { ReadOnlyRows, Transcript } from "./Transcript.tsx";
import { useClaudeChat } from "./useClaudeChat.ts";
import { PixieWork, SubagentWork, type WorkOf } from "./WorkViews.tsx";

export interface PaneChrome {
  // The grip, and the maximise and close buttons, from the workspace.
  grip: ReactNode;
  buttons: ReactNode;
  onMaximize: () => void;
  onClose: () => void;
  dimmed: boolean;
}

/** The pane's frame: its header, then its body, faded while another pane has the focus. */
function PaneFrame({
  chrome,
  label,
  header,
  children,
}: {
  chrome: PaneChrome;
  label: string;
  header: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={chrome.dimmed ? "dc-pane dimmed" : "dc-pane"} aria-label={label}>
      <HeaderFrame
        grip={chrome.grip}
        buttons={chrome.buttons}
        onMaximize={chrome.onMaximize}
        label={label}
      >
        {header}
      </HeaderFrame>
      <div className="dc-body">{children}</div>
    </section>
  );
}

interface ChatProps {
  id: string;
  chrome: PaneChrome;
  focus: number | null;
}

/** An open Nest chat. */
export function ChatPane({ id, chrome, focus }: ChatProps) {
  const { state, actions } = useStore();
  const shell = useShell();
  const session = state.sessions[id];
  const [loaded, setLoaded] = useState(false);
  const { onClose } = chrome;
  useEffect(() => {
    void actions.openChat(id).then(() => {
      setLoaded(true);
    });
    return () => {
      actions.closeChat(id);
    };
  }, [actions, id]);
  // Deleted, here or on another device.
  useEffect(() => {
    if (session === undefined && loaded) onClose();
  }, [session, loaded, onClose]);
  // A pixie's chat shows on its page; a habit run's chat shows here, read only (B42).
  const pixieOfChat = session?.habit_run_id == null ? session?.pixie_id : undefined;
  const { openPixie } = shell;
  useEffect(() => {
    if (pixieOfChat != null) {
      onClose();
      openPixie(pixieOfChat);
    }
  }, [pixieOfChat, openPixie, onClose]);

  if (session === undefined) {
    return (
      <PaneFrame chrome={chrome} label="Chat" header={<HeaderTitle title="" />}>
        <div className="dc-loading">
          <Fireflies size={12} />
        </div>
      </PaneFrame>
    );
  }
  return (
    <FileLinks folder={workRoot(session)}>
      <SessionBody session={session} chrome={chrome} focus={focus} />
    </FileLinks>
  );
}

function SessionBody({
  session,
  chrome,
  focus,
}: {
  session: Session;
  chrome: PaneChrome;
  focus: number | null;
}) {
  const { state, actions } = useStore();
  const shell = useShell();
  const id = session.id;
  const tracking = state.tracking[id];
  const background = tracking?.background ?? NO_BACKGROUND;
  const history = state.history[id] ?? "loading";
  const project = session.pixie_id == null;
  const membersOf = (team: string) =>
    Object.values(state.pixies)
      .filter((p) => p.team_id === team)
      .map((p) => p.id);
  return (
    <PaneFrame
      chrome={chrome}
      label={session.title}
      header={<ChatHeaderParts session={session} run={<RunControlView chat={id} />} />}
    >
      <Transcript
        session={session}
        background={background}
        focus={focus}
        history={history}
        onRetry={() => void actions.reloadChat(id)}
        dimmed={chrome.dimmed}
        nav={{
          openPixie: shell.openPixie,
          openTeamWork: project
            ? (team) => {
                shell.openWork({ team: { session: id, team, members: membersOf(team) } });
              }
            : null,
          openPixieWork: project
            ? (pixie) => {
                shell.openWork({ pixie: { session: id, pixie } });
              }
            : null,
          openChat: (chat) => {
            shell.openChat(chat);
          },
        }}
        bottom={
          <>
            {history === "loaded" && <BackgroundBar chat={id} summary={background} />}
            {session.habit_run_id == null && (
              <>
                <ReviewBar session={session} />
                <LimitBar session={session} />
                <AutopilotBar session={session} />
              </>
            )}
          </>
        }
      />
      {session.habit_run_id == null ? (
        <Composer target={{ kind: "chat", session }} />
      ) : (
        <p className="dc-readonly">A habit run. Its chat is read only.</p>
      )}
    </PaneFrame>
  );
}

/** A Claude Code or Codex chat: its history read only, and Continue in Nest. */
export function ClaudePane({
  id,
  chrome,
  onContinued,
}: {
  id: string;
  chrome: PaneChrome;
  // The Nest chat it became, shown in this pane.
  onContinued: (session: string) => void;
}) {
  const { state, actions } = useStore();
  const { chat, loaded, items } = useClaudeChat(id);
  const [adopting, setAdopting] = useState(false);
  const { onClose } = chrome;
  useEffect(() => {
    if (chat !== undefined) return;
    // Continued in Nest, here or on another device, or gone from its engine.
    const adopted = Object.values(state.sessions).find((s) => s.provider_session_id === id);
    if (adopted === undefined) onClose();
    else onContinued(adopted.id);
  }, [chat, state.sessions, id, onClose, onContinued]);
  const title = chat?.title ?? "Claude Code chat";
  const engine = chat === undefined ? "Claude Code" : outsideEngineName(chat);
  return (
    <PaneFrame
      chrome={chrome}
      label={`${title}, ${engine} chat`}
      header={
        <>
          <HeaderTitle title={title} />
          {chat?.open_in_claude_code === true && (
            <span className="dc-hstatus" title={`Open in ${engine}`}>
              <Dot tone="run" plain />
            </span>
          )}
          <span className="grow" />
        </>
      }
    >
      <div className="dc-txw">
        <div className="dc-tx from-end">
          <div className="dc-txin">
            {!loaded && (
              <p className="dc-empty">
                <Fireflies size={11} />
              </p>
            )}
            <ReadOnlyRows chat={`claude:${id}`} items={items} terminalPane={claudePane(id)} />
            {loaded && items.length === 0 && <p className="dc-empty">No messages yet</p>}
          </div>
        </div>
      </div>
      <div className="dc-continue">
        {chat?.open_in_claude_code === true && (
          <p className="dc-cwarn">
            <Glyph name="warning" size={10} />
            {`Open in ${engine} right now. Close it there before sending from here.`}
          </p>
        )}
        <div className="dc-crow2">
          <span className="dc-cnote">
            {chat === undefined
              ? "This chat is no longer listed."
              : "Read only. Continue it here to send messages."}
          </span>
          <Button
            kind="primary"
            disabled={chat === undefined || adopting}
            title="Turn it into a Nest chat in its own folder; the next message resumes it"
            onClick={() => {
              if (chat === undefined) return;
              setAdopting(true);
              void actions.adoptClaudeChat(chat).then((session) => {
                if (session === null) setAdopting(false);
              });
            }}
          >
            {adopting ? <Fireflies size={10} /> : <Glyph name="spark" size={10} />}
            Continue in Nest
          </Button>
        </div>
      </div>
    </PaneFrame>
  );
}

/** A subagent's work in a chat, read-only. */
export function AgentPane({
  session,
  call,
  chrome,
}: {
  session: string;
  call: string;
  chrome: PaneChrome;
}) {
  const { state } = useStore();
  const shell = useShell();
  const agent = state.tracking[session]?.agents.find((a) => a.id === call);
  return (
    <PaneFrame
      chrome={chrome}
      label={agent?.name ?? "Subagent"}
      header={
        <WorkHeader title={agent?.name ?? "Subagent"} running={agent?.status === "running"} />
      }
    >
      <div className="dc-tx">
        <div className="dc-txin">
          <SubagentWork
            session={session}
            call={call}
            onOpenChat={(id) => {
              shell.openChat(id);
            }}
          />
        </div>
      </div>
    </PaneFrame>
  );
}

/** A pixie's or a team's work in a chat, read-only. */
export function WorkPane({
  session,
  who,
  chrome,
}: {
  session: string;
  who: WorkOf;
  chrome: PaneChrome;
}) {
  const { state } = useStore();
  const shell = useShell();
  const pixie = "pixie" in who ? state.pixies[who.pixie] : undefined;
  const team = "team" in who ? state.teams[who.team] : undefined;
  const name = pixie?.name ?? team?.name ?? ("team" in who ? "Team" : "Pixie");
  return (
    <PaneFrame
      chrome={chrome}
      label={name}
      header={
        <>
          {pixie !== undefined && <Sprite mascot={pixie.mascot} color={pixie.color} size={14} />}
          <HeaderTitle title={name} />
          <span className="grow" />
        </>
      }
    >
      <div className="dc-tx">
        <div className="dc-txin">
          <PixieWork
            session={session}
            who={who}
            onOpenChat={(id) => {
              shell.openChat(id);
            }}
          />
        </div>
      </div>
    </PaneFrame>
  );
}

function WorkHeader({ title, running }: { title: string; running: boolean }) {
  return (
    <>
      <Glyph name="agent" size={11} className="dc-t3" />
      <HeaderTitle title={title} />
      {running && (
        <span className="dc-hstatus">
          <Dot tone="run" label="Working" />
        </span>
      )}
      <span className="grow" />
    </>
  );
}

/** A new chat's pane: "New chat" where the transcript will be, then its composer. */
export function DraftPane({
  repo,
  place,
  chrome,
  onCreated,
}: {
  repo: string;
  // Where it opened to start, for this one chat; null follows the selected place.
  place: NewChatChoice | null;
  chrome: PaneChrome;
  onCreated: (session: Session) => void;
}) {
  return (
    <PaneFrame
      chrome={chrome}
      label="New chat"
      header={
        <>
          <HeaderTitle title="New chat" />
          <span className="grow" />
        </>
      }
    >
      <p className="dc-newph">New chat</p>
      <Composer target={{ kind: "draft", repo, place, onCreated }} />
    </PaneFrame>
  );
}
