// A chat pane's header, as the Mac's PaneHeader (PaneView.swift): the grip, the chat's
// name and status dot, where it works in its branch's colour, the engine or local model, the machine of a General chat and who
// started it; at the trailing edge the issue and pull request chips, Stuck, the Run
// control, maximise and close. A double click on its empty part maximises the pane.
import type { CSSProperties, ReactNode } from "react";
import type { Session } from "../../api/types.ts";
import { isLocalModel } from "../../api/payloads.ts";
import { placeName, sessionPlace } from "../../screens/chat/place.ts";
import { startedByText } from "../../screens/pixies/options.ts";
import { useStore } from "../../store/context.ts";
import { GENERAL, repoNamed } from "../../store/general.ts";
import { localModelOf } from "../../store/local.ts";
import { chatStatus, engineName, pendingFor, shownTitle } from "../../store/selectors.ts";
import { Dot } from "../../ui/bits.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { PrChip } from "../shell/frame/PrChip.tsx";
import { placeColor } from "../shell/frame/projectMap.ts";
import { useBranchMap } from "./branchMaps.ts";
import { useFit } from "./fit.ts";
import { Glyph } from "./glyphs.tsx";

interface FrameProps {
  // The grip that drags the pane, and its maximise and close buttons.
  grip: ReactNode;
  buttons: ReactNode;
  onMaximize: () => void;
  children: ReactNode;
  // Named for assistive technology.
  label: string;
}

/** The header's frame: the double click lives behind its content, so buttons never wait. */
export function HeaderFrame({ grip, buttons, onMaximize, children, label }: FrameProps) {
  return (
    <header
      className="dc-head"
      aria-label={label}
      onDoubleClick={(event) => {
        if ((event.target as HTMLElement).closest("button, a, input") === null) onMaximize();
      }}
    >
      {grip}
      {children}
      {buttons}
    </header>
  );
}

/** The chat's name, in grey while another pane has the focus (B93). */
export function HeaderTitle({ title }: { title: string }) {
  return <h2 className="dc-htitle">{title}</h2>;
}

/** Where the chat works, beside its name: the branch icon and the worktree's name or the
 * folder's branch, in its branch map colour, shortened in the middle only when short of room. */
function HeaderPlace({ session }: { session: Session }) {
  const { state } = useStore();
  const repo = repoNamed(state.repos, session.repo);
  const map = useBranchMap(session.repo, repo?.git === true);
  const place = sessionPlace(session, repo);
  if (place === null) return null;
  const color = placeColor(map, place);
  const help =
    place.kind === "worktree" ? `Worktree ${place.name}` : `Project folder, on ${placeName(place)}`;
  return (
    <span
      className="dc-hplace"
      title={help}
      style={color === null ? undefined : ({ "--lane": color } as CSSProperties)}
    >
      <Glyph name="branch" size={11} />
      {/* A label on a plain span is not read; this text is (B147). */}
      <span className="sr">{help}</span>
      <span aria-hidden="true">{placeName(place)}</span>
    </span>
  );
}

export function ChatHeaderParts({ session, run }: { session: Session; run: ReactNode }) {
  const { state } = useStore();
  const fit = useFit();
  const status = chatStatus(session, pendingFor(state, session.id));
  const local = isLocalModel(session.model) ? localModelOf(state.local, session.model) : null;
  const engine = session.provider === "claude" ? null : engineName(state, session.provider);
  const pixie =
    session.started_by_pixie === null ? undefined : state.pixies[session.started_by_pixie];
  const started = session.started_by_pixie === null ? null : startedByText(pixie?.name);
  return (
    <>
      <HeaderTitle title={shownTitle(session)} />
      <span className="dc-hstatus" title={status.label}>
        <Dot tone={status.tone} label={status.label} />
      </span>
      <HeaderPlace session={session} />
      {local !== null ? (
        <span
          className="dc-hlocal"
          title={`Runs on ${local.name} at ${local.address}, through ${engineName(state, session.provider)}`}
        >
          <span className="dc-hlocalt">Local</span>
          <span>{`${local.name} · ${engineName(state, session.provider)}`}</span>
        </span>
      ) : (
        engine !== null && (
          <span className="dc-hmeta" title={`Runs on ${engine}`}>
            {engine}
          </span>
        )
      )}
      {session.repo === GENERAL && (
        <span className="dc-hmeta" title={`Runs on ${state.machine ?? "this computer"}`}>
          <Glyph name="machine" size={11} />
          {state.machine ?? "This computer"}
        </span>
      )}
      {started !== null && (
        <span className="dc-hmeta dc-hstarted" title={started} aria-label={started}>
          {pixie !== undefined && <Sprite mascot={pixie.mascot} color={pixie.color} size={11} />}
          <span>{fit.showsHeaderDetails ? started : (pixie?.name ?? started)}</span>
        </span>
      )}
      <span className="grow" />
      {fit.showsPullRequest && session.issue !== null && (
        <a
          className="dc-hchip"
          href={session.issue.url}
          target="_blank"
          rel="noreferrer"
          title={`Issue #${String(session.issue.number)}: ${session.issue.title}. Open on GitHub`}
          aria-label={`Issue ${String(session.issue.number)}, ${session.issue.title}`}
        >
          <Glyph name="issue" size={10} />
          <span>#{session.issue.number}</span>
        </a>
      )}
      {fit.showsPullRequest && session.pr !== null && <PrChip session={session} pr={session.pr} />}
      {session.stuck !== null && (
        <span
          className="dc-stuck"
          title={session.stuck.details}
          aria-label={`Stuck: ${session.stuck.details}`}
        >
          Stuck
        </span>
      )}
      {run}
    </>
  );
}
