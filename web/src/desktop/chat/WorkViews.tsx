// What a subagent, pixie or team did in a chat, read-only (B46), as the Mac's WorkSheet
// content: each call with what it was asked, its messages and tool calls as the chat shows
// them, and its report, live while it works. Follow-ups go in the chat.
import { useEffect, useMemo, useState } from "react";
import type {
  AgentMessage,
  AgentWork,
  CallState,
  CallWork,
  GroupEntry,
  NestEvent,
} from "../../api/types.ts";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { ago } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import { lastEvent, liveMessages } from "../../transcript/agentWork.ts";
import { buildTranscript, type TranscriptItem } from "../../transcript/build.ts";
import { agentReport } from "../../transcript/report.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { AssistantText, SystemLine } from "./Rows.tsx";
import { ReadOnlyRows } from "./Transcript.tsx";

const STATES: Record<CallState, string> = {
  running: "working",
  done: "done",
  failed: "failed",
  interrupted: "stopped",
};

const READ_ONLY = new Set(["approval", "pixie", "card", "artifact"]);

/** The messages as transcript rows. */
function workItems(messages: AgentMessage[], root: string | null): TranscriptItem[] {
  const events: NestEvent[] = messages.map((m) => ({
    id: m.event_id,
    type: "session.message",
    ts: m.ts,
    session_id: null,
    payload: { blocks: m.blocks, parent_tool_use_id: null },
  }));
  return buildTranscript(events, {}, root).filter((item) => !READ_ONLY.has(item.kind));
}

interface CallProps {
  chat: string;
  prompt: string | null;
  messages: AgentMessage[];
  report: string | null;
  running: boolean;
  root: string | null;
}

/** One call: what it was asked, its messages, Working while it runs, then its report. */
function CallBody({ chat, prompt, messages, report, running, root }: CallProps) {
  const items = useMemo(() => workItems(messages, root), [messages, root]);
  return (
    <>
      {prompt !== null && prompt !== "" && (
        <div className="dc-asked">
          <span className="dc-label">Asked</span>
          <AssistantText text={prompt} copyable={false} />
        </div>
      )}
      <ReadOnlyRows chat={chat} items={items} />
      {running && (
        <p className="dc-wline static">
          <Fireflies size={10} />
          {items.length === 0 ? "Starting" : "Working"}
        </p>
      )}
      {report !== null && report !== "" ? (
        <div className="dc-report">
          <span className="dc-label">Report</span>
          <AssistantText text={agentReport(report)} />
        </div>
      ) : (
        !running && <SystemLine text="Ended without a report" />
      )}
    </>
  );
}

/** Where the work came from, and that it is read-only. */
function WorkHead({
  kind,
  session,
  onOpenChat,
}: {
  kind: string;
  session: string;
  onOpenChat?: (id: string) => void;
}) {
  const { state } = useStore();
  const title = state.sessions[session]?.title ?? "this chat";
  return (
    <p className="dc-workhead">
      <span>{kind} in</span>
      {onOpenChat === undefined ? (
        <span>{title}</span>
      ) : (
        <button
          className="dc-linkbtn"
          title="Open the chat; follow-ups go there"
          onClick={() => {
            onOpenChat(session);
          }}
        >
          {title}
        </button>
      )}
      <span className="grow" />
      <span>Read-only</span>
    </p>
  );
}

/** A subagent's whole transcript (B46), its new messages following from the chat's events. */
export function SubagentWork({
  session,
  call,
  onOpenChat,
}: {
  session: string;
  call: string;
  onOpenChat?: (id: string) => void;
}) {
  const { state, actions } = useStore();
  const chat = state.sessions[session];
  const agent = state.tracking[session]?.agents.find((a) => a.id === call);
  const [work, setWork] = useState<AgentWork | null | undefined>(undefined);
  const status = agent?.status;
  useEffect(() => {
    void actions.openChat(session);
    return () => {
      actions.closeChat(session);
    };
  }, [actions, session]);
  useEffect(() => {
    let current = true;
    void actions.agentTranscript(session, call).then((loaded) => {
      if (current) setWork(loaded);
    });
    return () => {
      current = false;
    };
  }, [actions, session, call, status]);
  const messages =
    work == null
      ? []
      : [
          ...work.messages,
          ...liveMessages(state.transcripts[session], call, lastEvent(work.messages)),
        ];
  return (
    <div className="dc-work">
      <WorkHead
        kind="Subagent"
        session={session}
        {...(onOpenChat === undefined ? {} : { onOpenChat })}
      />
      {work === undefined && (
        <p className="dc-wline static">
          <Fireflies size={10} />
          Loading
        </p>
      )}
      {work === null && <SystemLine text="Could not load this work" />}
      {work != null && (
        <CallBody
          chat={`${session}|${call}`}
          prompt={work.prompt}
          messages={messages}
          report={work.report}
          running={status === "running"}
          root={workRoot(chat)}
        />
      )}
    </div>
  );
}

export type WorkOf = { pixie: string } | { team: string };

function entryOf(group: GroupEntry[], who: WorkOf): GroupEntry | undefined {
  if ("team" in who) return group.find((e) => e.team_id === who.team);
  return (
    group.find((e) => e.pixie_id === who.pixie) ??
    group.find((e) => e.members.some((m) => m.pixie_id === who.pixie))
  );
}

/** Each call's messages that arrived since its snapshot, on its newest running call. */
function withLive(calls: CallWork[], events: NestEvent[] | undefined): CallWork[] {
  const agents = new Map<string, { calls: CallWork[]; first: CallWork }>();
  for (const call of calls) {
    const key = call.agent_id ?? call.tool_use_id;
    agents.set(key, { calls: [...(agents.get(key)?.calls ?? []), call], first: call });
  }
  const extra = new Map<string, AgentMessage[]>();
  for (const { calls: same, first } of agents.values()) {
    const target = same.find((c) => c.state === "running");
    if (target === undefined) continue;
    extra.set(
      target.id,
      liveMessages(events, first.tool_use_id, lastEvent(same.flatMap((c) => c.messages))),
    );
  }
  return calls.map((c) => {
    const more = extra.get(c.id) ?? [];
    return more.length === 0 ? c : { ...c, messages: [...c.messages, ...more] };
  });
}

/** A pixie's or a team's work in a chat (B46): every call newest first, live while it runs. */
export function PixieWork({
  session,
  who,
  onOpenChat,
}: {
  session: string;
  who: WorkOf;
  onOpenChat?: (id: string) => void;
}) {
  const { state, actions } = useStore();
  const chat = state.sessions[session];
  const entry = entryOf(state.pixieGroups[session] ?? [], who);
  const [calls, setCalls] = useState<CallWork[] | null | undefined>(undefined);
  const ids =
    "pixie" in who
      ? [who.pixie]
      : (entry?.members ?? []).filter((m) => m.state !== null).map((m) => m.pixie_id);
  const idsKey = ids.join(" ");
  const version = (entry?.calls ?? []).map((c) => `${c.id}:${c.state}`).join(" ");
  useEffect(() => {
    void actions.openChat(session);
    return () => {
      actions.closeChat(session);
    };
  }, [actions, session]);
  useEffect(() => {
    let current = true;
    const pixieIds = idsKey.split(" ").filter(Boolean);
    void Promise.all(pixieIds.map((id) => actions.pixieCalls(session, id))).then((loaded) => {
      if (!current) return;
      const read = loaded.filter((each) => each !== null);
      const all = read.flat().sort((a, b) => b.started_at.localeCompare(a.started_at));
      setCalls(read.length === loaded.length ? all : null);
    });
    return () => {
      current = false;
    };
  }, [actions, session, idsKey, version]);
  const teamCalls = "team" in who ? new Set(entry?.calls.map((c) => c.id)) : null;
  const shown = withLive(
    (calls ?? []).filter((c) => teamCalls?.has(c.id) ?? true),
    state.transcripts[session],
  );
  const now = new Date();
  return (
    <div className="dc-work">
      <WorkHead
        kind={"team" in who ? "Team" : "Pixie"}
        session={session}
        {...(onOpenChat === undefined ? {} : { onOpenChat })}
      />
      {calls === undefined && (
        <p className="dc-wline static">
          <Fireflies size={10} />
          Loading
        </p>
      )}
      {calls === null && <SystemLine text="Could not load this work" />}
      {calls != null && shown.length === 0 && <SystemLine text="No calls in this chat yet" />}
      {shown.map((call, index) => {
        const by = state.pixies[call.pixie_id];
        const running = call.state === "running";
        return (
          <section key={call.id} className={index > 0 ? "dc-call sep" : "dc-call"}>
            <header className="dc-callh">
              {by !== undefined && (
                <>
                  <Sprite
                    mascot={by.mascot}
                    color={by.color}
                    size={14}
                    working={running}
                    phaseKey={by.id}
                  />
                  <span className="dc-callby" style={{ color: by.color }}>
                    {by.name}
                  </span>
                </>
              )}
              <span className="dc-quiet">
                {ago(call.started_at, now) === "now"
                  ? "Called now"
                  : `Called ${ago(call.started_at, now)} ago`}
              </span>
              {call.continued && (
                <span
                  className="dc-cont"
                  title="It went on from its earlier call in this chat, with that work in mind"
                >
                  Continued
                </span>
              )}
              <span className="grow" />
              <span className={call.state === "failed" ? "dc-bad" : "dc-quiet"}>
                {STATES[call.state]}
              </span>
            </header>
            <CallBody
              chat={`${session}|${call.id}`}
              prompt={call.prompt}
              messages={call.messages}
              report={call.report}
              running={running}
              root={workRoot(chat)}
            />
          </section>
        );
      })}
    </div>
  );
}
