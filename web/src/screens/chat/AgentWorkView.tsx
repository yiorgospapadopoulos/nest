import { useEffect, useState } from "react";
import type { AgentWork, TrackedAgent } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { ChatStatus } from "../../store/selectors.ts";
import { workRoot } from "../approvals/hooks.ts";
import { Frame } from "./Frame.tsx";
import { lastEvent, liveMessages } from "../../transcript/agentWork.ts";
import { WorkBody } from "./WorkBody.tsx";

const STATUS: Record<TrackedAgent["status"], ChatStatus> = {
  running: { tone: "run", label: "Working" },
  done: { tone: "done", label: "Done" },
  failed: { tone: "fail", label: "Failed" },
};

interface Props {
  sessionId: string;
  // The Agent call that started the subagent.
  call: string;
  onBack: () => void;
}

/**
 * A subagent's whole transcript, read only (B46): what it was asked, its tool calls and
 * results, and its report. While it runs, its new messages follow from the chat's events;
 * the report is read again once it finishes. Follow-ups go through the main chat.
 */
export function AgentWorkView({ sessionId, call, onBack }: Props) {
  const { state, actions } = useStore();
  const session = state.sessions[sessionId];
  const agent = state.tracking[sessionId]?.agents.find((a) => a.id === call);
  // Undefined while it loads; null when it could not be read.
  const [work, setWork] = useState<AgentWork | null | undefined>(undefined);
  const status = agent?.status;

  // The chat's events, so the subagent's new messages show as they arrive.
  useEffect(() => {
    void actions.openChat(sessionId);
    return () => {
      actions.closeChat(sessionId);
    };
  }, [actions, sessionId]);

  useEffect(() => {
    let current = true;
    void actions.agentTranscript(sessionId, call).then((loaded) => {
      if (current) setWork(loaded);
    });
    return () => {
      current = false;
    };
  }, [actions, sessionId, call, status]);

  const messages =
    work == null
      ? []
      : [
          ...work.messages,
          ...liveMessages(state.transcripts[sessionId], call, lastEvent(work.messages)),
        ];

  return (
    <Frame
      title={agent?.name ?? "Subagent"}
      {...(status === undefined ? {} : { status: STATUS[status] })}
      back={session?.title ?? "Chat"}
      onBack={onBack}
      details={
        agent?.description != null && (
          <div className="ch-r2">
            <span className="wk-desc">{agent.description}</span>
          </div>
        )
      }
    >
      <div className="ch-tx">
        {work === undefined && <p className="note">Loading...</p>}
        {work === null && <p className="note">This subagent&apos;s work could not be read.</p>}
        {work != null && (
          <WorkBody
            prompt={work.prompt}
            messages={messages}
            report={work.report}
            running={status === "running"}
            root={workRoot(session)}
          />
        )}
        <p className="note wk-ro">Read only. Ask follow-ups in the chat.</p>
      </div>
    </Frame>
  );
}
