import { useEffect, useMemo, useState, type ReactNode } from "react";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { buildTranscript, type TranscriptItem } from "../../transcript/build.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { TranscriptRow } from "../chat/Rows.tsx";
import { RowsContext, useRows, type ChatRows } from "../chat/rowsContext.ts";
import { PixieWork, SubagentWork } from "../chat/WorkViews.tsx";
import { SheetFrame } from "../sheets/SheetFrame.tsx";
import { useShell, type WorkTarget } from "../shell/context.ts";
import "./sheets.css";

/** The sheets the window draws over everything: a habit run's chat, or a chat's work. */
export function ShellSheets() {
  const shell = useShell();
  const sheet = shell.sheet;
  if (sheet === null) return null;
  if ("habitRun" in sheet) return <HabitRunSheet key={sheet.habitRun} session={sheet.habitRun} />;
  return <WorkSheet key={JSON.stringify(sheet.work)} target={sheet.work} />;
}

/** Follows the chat's events while the sheet shows, unless a pane already does. */
function useChatEvents(session: string): void {
  const { state, actions } = useStore();
  const [followed] = useState(() => state.transcripts[session] !== undefined);
  useEffect(() => {
    if (followed) return;
    void actions.openChat(session);
    return () => {
      actions.closeChat(session);
    };
  }, [actions, session, followed]);
}

/** The rows' context for a read-only transcript of `session`: nothing to stop or edit. */
function ReadOnly({ session, children }: { session: string; children: ReactNode }) {
  const { state } = useStore();
  const shell = useShell();
  const outer = useRows();
  const rows: ChatRows = {
    ...outer,
    chat: session,
    session: state.sessions[session],
    stopper: null,
    messageActions: null,
    terminalPane: null,
    openPixie: (id) => {
      shell.closeSheet();
      shell.openPixie(id);
    },
    openChat: (id) => {
      shell.closeSheet();
      shell.openChat(id);
    },
  };
  return <RowsContext value={rows}>{children}</RowsContext>;
}

function Rows({ items }: { items: TranscriptItem[] }) {
  return (
    <div className="pw-rows">
      {items.map((item) => (
        <TranscriptRow key={item.key} item={item} />
      ))}
    </div>
  );
}

/** A habit run's chat, read-only: its transcript without a composer (HabitRunSheet). */
function HabitRunSheet({ session }: { session: string }) {
  const { state } = useStore();
  const shell = useShell();
  useChatEvents(session);
  const chat = state.sessions[session];
  const events = state.transcripts[session];
  const pixies = useMemo(
    () => new Map(Object.values(state.pixies).map((p) => [p.slug, p])),
    [state.pixies],
  );
  const items = useMemo(
    () => buildTranscript(events ?? [], state.approvals, workRoot(chat), undefined, pixies),
    [events, state.approvals, chat, pixies],
  );
  return (
    <SheetFrame title="Habit run" width={720} maxHeight={600} onClose={shell.closeSheet}>
      <div className="pw-sub">
        <span className="pw-sub-t">{chat?.title}</span>
        <span>Read-only</span>
      </div>
      <ReadOnly session={session}>
        {events === undefined ? (
          <p className="pw-wait">
            <Fireflies size={11} />
            Loading
          </p>
        ) : (
          <Rows items={items} />
        )}
      </ReadOnly>
    </SheetFrame>
  );
}

/**
 * What a subagent, pixie or team did in a chat, read-only (B46, WorkSheet.swift), drawn by
 * the chat's own work views; the chat's name opens the chat, where follow-ups go.
 */
function WorkSheet({ target }: { target: WorkTarget }) {
  const { state } = useStore();
  const shell = useShell();
  const openChat = (id: string) => {
    shell.closeSheet();
    shell.openChat(id);
  };
  let title: string;
  let body: ReactNode;
  if ("subagent" in target) {
    const { session, tool } = target.subagent;
    title = state.tracking[session]?.agents.find((a) => a.id === tool)?.name ?? "Subagent";
    body = <SubagentWork session={session} call={tool} onOpenChat={openChat} />;
  } else if ("pixie" in target) {
    const { session, pixie } = target.pixie;
    title = state.pixies[pixie]?.name ?? "Pixie";
    body = <PixieWork session={session} who={{ pixie }} onOpenChat={openChat} />;
  } else {
    const { session, team } = target.team;
    title = state.teams[team]?.name ?? "Team";
    body = <PixieWork session={session} who={{ team }} onOpenChat={openChat} />;
  }
  return (
    <SheetFrame title={title} width={700} maxHeight={820} onClose={shell.closeSheet}>
      {body}
    </SheetFrame>
  );
}
