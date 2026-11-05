// A pixie's pane in the Pixies tab's workspace, as the Mac's PixiePane.swift (B37): its one
// ongoing chat (D072) in the same chrome as a chat's pane. The header has the grip, the
// sprite, the name, @slug and the chat's status, then Details, maximise and close.
import { useEffect, useRef } from "react";
import type { Pixie, Session } from "../../api/types.ts";
import { workRoot } from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { chatStatus, pendingFor, pixieWorking } from "../../store/selectors.ts";
import { NO_BACKGROUND } from "../../store/state.ts";
import { Dot } from "../../ui/bits.tsx";
import { AutopilotBar, LimitBar, ReviewBar } from "../chat/Bars.tsx";
import type { PaneChrome } from "../chat/ChatPane.tsx";
import { Composer } from "../chat/Composer.tsx";
import { FileLinks } from "../chat/FileLinks.tsx";
import { useFit } from "../chat/fit.ts";
import { HeaderFrame, HeaderTitle } from "../chat/PaneHeader.tsx";
import { Transcript } from "../chat/Transcript.tsx";
import { useShell } from "../shell/context.ts";
import { Sprite } from "./Sprite.tsx";
import "./pane.css";

interface Props {
  id: string;
  chrome: PaneChrome;
  // The pane has the focus, for whether Details shows as on.
  focused: boolean;
}

export function PixiePane({ id, chrome, focused }: Props) {
  const { state, actions } = useStore();
  const shell = useShell();
  const pixie = state.pixies[id];
  const seen = useRef(false);
  const { onClose } = chrome;

  // A pixie deleted here or on another device leaves the workspace.
  useEffect(() => {
    if (pixie !== undefined) seen.current = true;
    else if (seen.current) onClose();
  }, [pixie, onClose]);

  // Its reports are read once its pane is on screen, as reports arrive too (B42).
  const unread = Object.values(state.reports)
    .filter((r) => r.pixie_id === id && r.read_at === null)
    .map((r) => r.id)
    .join(" ");
  const flagged = (pixie?.unread_action_reports ?? 0) > 0;
  useEffect(() => {
    if ((unread === "" && !flagged) || document.visibilityState !== "visible") return;
    void actions.readPixieReports(id, unread === "" ? [] : unread.split(" "));
  }, [actions, id, unread, flagged]);

  const chat = pixie?.chat_session_id ?? null;
  useEffect(() => {
    if (chat === null) return;
    void actions.openChat(chat);
    return () => {
      actions.closeChat(chat);
    };
  }, [actions, chat]);

  if (pixie === undefined) {
    return (
      <section className="dc-pane" aria-label="Pixie">
        <HeaderFrame
          grip={chrome.grip}
          buttons={chrome.buttons}
          onMaximize={chrome.onMaximize}
          label="Pixie"
        >
          <HeaderTitle title="" />
        </HeaderFrame>
        <div className="dc-body" />
      </section>
    );
  }
  const session = chat === null ? undefined : state.sessions[chat];
  return (
    <section className={chrome.dimmed ? "dc-pane dimmed" : "dc-pane"} aria-label={pixie.name}>
      <HeaderFrame
        grip={chrome.grip}
        buttons={
          <>
            <DetailsButton pixie={pixie} focused={focused} />
            {chrome.buttons}
          </>
        }
        onMaximize={chrome.onMaximize}
        label={pixie.name}
      >
        <PixieHeaderParts pixie={pixie} session={session} />
      </HeaderFrame>
      <div className="dc-body">
        <FileLinks folder={workRoot(session)}>
          {session === undefined ? (
            <div className="dc-tx dpx-hi-wrap">{chat === null && <SayHi pixie={pixie} />}</div>
          ) : (
            <Transcript
              key={session.id}
              session={session}
              background={state.tracking[session.id]?.background ?? NO_BACKGROUND}
              focus={null}
              history={state.history[session.id] ?? "loading"}
              onRetry={() => void actions.reloadChat(session.id)}
              dimmed={chrome.dimmed}
              nav={{
                openPixie: shell.openPixie,
                openTeamWork: null,
                openPixieWork: null,
                openChat: (other) => {
                  shell.openChat(other);
                },
              }}
              bottom={
                <>
                  <ReviewBar session={session} />
                  <LimitBar session={session} />
                  <AutopilotBar session={session} />
                </>
              }
            />
          )}
        </FileLinks>
        <Composer target={{ kind: "pixie", pixie: pixie.id, session }} />
      </div>
    </section>
  );
}

function PixieHeaderParts({ pixie, session }: { pixie: Pixie; session: Session | undefined }) {
  const { state } = useStore();
  const fit = useFit();
  const status = session === undefined ? null : chatStatus(session, pendingFor(state, session.id));
  return (
    <>
      <Sprite
        mascot={pixie.mascot}
        color={pixie.color}
        size={16}
        working={pixieWorking(state, pixie)}
        phaseKey={pixie.id}
      />
      <HeaderTitle title={pixie.name} />
      {fit.showsHeaderDetails && <span className="dpx-slug">@{pixie.slug}</span>}
      {status !== null && (
        // A plain dot: the sprite beside it already hops while the pixie works.
        <span className="dc-hstatus dpx-status" title={status.label}>
          <Dot tone={status.tone} plain />
          {!fit.compact && <span>{status.label}</span>}
        </span>
      )}
      <span className="grow" />
    </>
  );
}

/** Shows this pixie's details on the right, or hides them while they show. */
function DetailsButton({ pixie, focused }: { pixie: Pixie; focused: boolean }) {
  const shell = useShell();
  const fit = useFit();
  const showing = shell.pixieDetailsOpen && focused;
  return (
    <button
      className={`dk-btn ${showing ? "k-soft" : "k-plain"}${fit.showsDetailsLabel ? "" : " icon"} dpx-details`}
      title={showing ? "Hide details" : "Show details"}
      aria-label="Details"
      aria-pressed={showing}
      onClick={() => {
        shell.togglePixieDetails(pixie.id);
      }}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <rect x="2" y="3" width="12" height="10" rx="2" />
        <path d="M10 3v10" />
      </svg>
      {fit.showsDetailsLabel && <span>Details</span>}
    </button>
  );
}

/** Before the first message: the big sprite and a hello. */
function SayHi({ pixie }: { pixie: Pixie }) {
  return (
    <div className="dpx-hi">
      <Sprite mascot={pixie.mascot} color={pixie.color} size={64} />
      <b>Say hi to {pixie.name}</b>
      <span>It remembers what matters across chats.</span>
    </div>
  );
}
