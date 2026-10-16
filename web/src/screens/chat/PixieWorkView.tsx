import { useEffect, useState } from "react";
import type { CallState, CallWork, GroupEntry, NestEvent } from "../../api/types.ts";
import { ago } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import type { ChatStatus } from "../../store/selectors.ts";
import { workRoot } from "../approvals/hooks.ts";
import { Sprite } from "../pixies/Sprite.tsx";
import { TeamFace } from "../pixies/TeamFace.tsx";
import type { WorkOf } from "../projects/ChatTree.tsx";
import { Frame } from "./Frame.tsx";
import { lastEvent, liveMessages } from "../../transcript/agentWork.ts";
import { WorkBody } from "./WorkBody.tsx";

const STATUS: Record<CallState, ChatStatus> = {
  running: { tone: "run", label: "Working" },
  done: { tone: "done", label: "Done" },
  failed: { tone: "fail", label: "Failed" },
  interrupted: { tone: "int", label: "Stopped" },
};

interface Props {
  sessionId: string;
  who: WorkOf;
  onBack: () => void;
}

/** The chat's group entry that holds the pixie (alone or in its team), or the team. */
function entryOf(group: GroupEntry[], who: WorkOf): GroupEntry | undefined {
  if ("team" in who) return group.find((e) => e.team_id === who.team);
  return (
    group.find((e) => e.pixie_id === who.pixie) ??
    group.find((e) => e.members.some((m) => m.pixie_id === who.pixie))
  );
}

/** Whether the pixie's latest call in the entry, alone or with its team, runs (B48). */
function callRunning(entry: GroupEntry | undefined, pixieId: string): boolean {
  if (entry?.kind === "team") {
    return entry.members.some((m) => m.pixie_id === pixieId && m.state === "running");
  }
  return entry?.state === "running";
}

/**
 * Each call's messages that arrived since its snapshot. A continued agent's messages name
 * its first call as their parent, so they go to its newest call that is still running.
 */
function withLive(calls: CallWork[], events: NestEvent[] | undefined): CallWork[] {
  // Each agent's calls, newest first, and its first call, whose id its messages carry.
  const agents = new Map<string, { calls: CallWork[]; first: CallWork }>();
  for (const call of calls) {
    const key = call.agent_id ?? call.tool_use_id;
    const same = agents.get(key)?.calls ?? [];
    agents.set(key, { calls: [...same, call], first: call });
  }
  const extra = new Map<string, CallWork["messages"]>();
  for (const { calls: same, first } of agents.values()) {
    const target = same.find((c) => c.state === "running");
    if (target === undefined) continue;
    const after = lastEvent(same.flatMap((c) => c.messages));
    extra.set(target.id, liveMessages(events, first.tool_use_id, after));
  }
  return calls.map((c) => {
    const more = extra.get(c.id) ?? [];
    return more.length === 0 ? c : { ...c, messages: [...c.messages, ...more] };
  });
}

/**
 * A pixie's work in a chat, or a team's (all its pixies' calls), read only (B46): every
 * call newest first with its messages and report; a call that continued the same agent
 * is marked. Read again whenever the chat's group changes; new messages of running calls
 * follow from the chat's events. Follow-ups go through the main chat.
 */
export function PixieWorkView({ sessionId, who, onBack }: Props) {
  const { state, actions } = useStore();
  const session = state.sessions[sessionId];
  const entry = entryOf(state.pixieGroups[sessionId] ?? [], who);
  // Undefined while it loads; null when it could not be read.
  const [calls, setCalls] = useState<CallWork[] | null | undefined>(undefined);
  const pixie = "pixie" in who ? state.pixies[who.pixie] : undefined;
  const team = "team" in who ? state.teams[who.team] : undefined;
  // The pixies whose calls show, and the calls of the entry as they are now.
  const ids =
    "pixie" in who
      ? [who.pixie]
      : (entry?.members ?? []).filter((m) => m.state !== null).map((m) => m.pixie_id);
  const idsKey = ids.join(" ");
  const version = (entry?.calls ?? []).map((c) => `${c.id}:${c.state}`).join(" ");

  useEffect(() => {
    void actions.openChat(sessionId);
    return () => {
      actions.closeChat(sessionId);
    };
  }, [actions, sessionId]);

  useEffect(() => {
    let current = true;
    const pixieIds = idsKey.split(" ").filter(Boolean);
    void Promise.all(pixieIds.map((id) => actions.pixieCalls(sessionId, id))).then((loaded) => {
      if (!current) return;
      const read = loaded.filter((each) => each !== null);
      const all = read.flat().sort((a, b) => b.started_at.localeCompare(a.started_at));
      setCalls(read.length === loaded.length ? all : null);
    });
    return () => {
      current = false;
    };
  }, [actions, sessionId, idsKey, version]);

  // A team's page shows the calls made with the team.
  const teamCalls = "team" in who ? new Set(entry?.calls.map((c) => c.id)) : null;
  const shown = withLive(
    (calls ?? []).filter((c) => teamCalls?.has(c.id) ?? true),
    state.transcripts[sessionId],
  );
  const name = pixie?.name ?? team?.name ?? ("team" in who ? "A team" : "A pixie");
  const root = workRoot(session);

  return (
    <Frame
      title={name}
      icon={
        pixie !== undefined ? (
          <span aria-hidden="true">
            <Sprite
              mascot={pixie.mascot}
              color={pixie.color}
              size={22}
              working={callRunning(entry, pixie.id)}
              phaseKey={pixie.id}
            />
          </span>
        ) : (
          entry !== undefined &&
          entry.members.length > 0 && (
            <TeamFace members={entry.members} pixies={state.pixies} className="wkteam" size={11} />
          )
        )
      }
      {...(entry === undefined ? {} : { status: STATUS[entry.state] })}
      back={session?.title ?? "Chat"}
      onBack={onBack}
    >
      <div className="ch-tx">
        {entry === undefined && <p className="note">Not in this chat any more.</p>}
        {calls === undefined && <p className="note">Loading...</p>}
        {calls === null && <p className="note">This work could not be read.</p>}
        {calls != null && shown.length === 0 && <p className="note">No calls yet.</p>}
        {shown.map((call) => {
          const by = state.pixies[call.pixie_id];
          return (
            <section
              key={call.id}
              className="wkc gl"
              aria-label={`${call.continued ? "Continued call" : "Call"}, ${STATUS[call.state].label}`}
            >
              <header className="wkh">
                {"team" in who && by !== undefined && (
                  <span className="wkby">
                    <span aria-hidden="true">
                      <Sprite
                        mascot={by.mascot}
                        color={by.color}
                        size={16}
                        working={call.state === "running"}
                        phaseKey={by.id}
                      />
                    </span>
                    {by.name}
                  </span>
                )}
                {call.continued && <span className="wkcont">Continued</span>}
                <span className={call.state === "failed" ? "ctw bad" : "ctw"}>
                  {STATUS[call.state].label}
                </span>
                <span className="flex" />
                <span className="ago">{ago(call.started_at, new Date())}</span>
              </header>
              <WorkBody
                prompt={call.prompt}
                messages={call.messages}
                report={call.report}
                running={call.state === "running"}
                root={root}
              />
            </section>
          );
        })}
        <p className="note wk-ro">Read only. Ask follow-ups in the chat.</p>
      </div>
    </Frame>
  );
}
