import type { Session } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { chatStatus, pendingFor } from "../../store/selectors.ts";
import type { CardItem } from "../../transcript/build.ts";
import { ChoicesCard, ReportCard, SuggestionCard } from "./HabitCards.tsx";
import { Dot, Pill } from "../../ui/bits.tsx";
import { prView } from "./prView.ts";

// GitHub's review decisions, as a short phrase.
const REVIEWS: Record<string, string> = {
  APPROVED: "approved",
  CHANGES_REQUESTED: "changes requested",
  REVIEW_REQUIRED: "review required",
};

interface Props {
  item: CardItem;
  ev: string;
  // The pixie whose chat it is.
  pixieId: string;
  onOpenChat: (sessionId: string) => void;
}

/** A card a pixie posted in its chat, live from the store. */
export function PixieCard({ item, ev, pixieId, onOpenChat }: Props) {
  switch (item.card) {
    case "report":
      return <ReportCard reportId={item.reportId} ev={ev} />;
    case "choices":
      return (
        <ChoicesCard options={item.options} answered={item.answered} pixieId={pixieId} ev={ev} />
      );
    case "habit_suggestion":
      return <SuggestionCard habit={item.habit} pixieId={pixieId} ev={ev} />;
    default:
      return (
        <ChatCard card={item.card} sessionId={item.sessionId} ev={ev} onOpenChat={onOpenChat} />
      );
  }
}

interface ChatCardProps {
  card: "session" | "pr";
  sessionId: string;
  ev: string;
  onOpenChat: (sessionId: string) => void;
}

/**
 * A chat the pixie started with that chat's state, or that chat's pull request with its
 * checks and review (B41).
 */
function ChatCard({ card, sessionId, ev, onOpenChat }: ChatCardProps) {
  const { state } = useStore();
  const session = state.sessions[sessionId];
  const title = session?.title ?? "A chat";
  const label = card === "session" ? `Chat: ${title}` : `Pull request: ${title}`;
  return (
    <div className="pxcard" role="group" aria-label={label} data-ev={ev}>
      <div className="pxcb">
        {card === "session" ? (
          <SessionBody session={session} title={title} />
        ) : (
          <PrBody session={session} title={title} />
        )}
      </div>
      <div className="pxca">
        <button
          className="b qb2"
          onClick={() => {
            onOpenChat(sessionId);
          }}
        >
          Open
        </button>
        {card === "pr" && session?.pr_url != null && (
          <a
            className="b qb2"
            href={session.pr?.url ?? session.pr_url}
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
        )}
      </div>
    </div>
  );
}

function SessionBody({ session, title }: { session: Session | undefined; title: string }) {
  const { state } = useStore();
  if (session === undefined) return <b>{title}</b>;
  const status = chatStatus(session, pendingFor(state, session.id));
  return (
    <>
      <b>{title}</b>
      <span className="pxcm">
        {session.repo}
        <Pill tone={status.tone} label={status.label} />
      </span>
    </>
  );
}

function PrBody({ session, title }: { session: Session | undefined; title: string }) {
  if (session?.pr_url == null) {
    return (
      <>
        <b>{title}</b>
        <span className="pxcm">No pull request yet</span>
      </>
    );
  }
  const pr = session.pr;
  const view = prView(pr, session.pr_url);
  const decision = pr?.review_decision ?? null;
  return (
    <>
      <b>
        {view.label} {pr?.title ?? title}
      </b>
      <span className="pxcm">
        <Dot tone={view.tone} />
        {view.text}
        {decision !== null && `, ${REVIEWS[decision] ?? decision.toLowerCase()}`}
      </span>
    </>
  );
}
