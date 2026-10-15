import { useStore } from "../../store/context.ts";
import { inboxGroups } from "../../store/selectors.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { InboxCard } from "./InboxCard.tsx";
import { CiFailureCard } from "./PrCards.tsx";
import { ReportCard } from "./ReportCard.tsx";
import { StuckCard } from "./StuckCard.tsx";

// A pixie chat's repo; its items are grouped under the pixie (D072).
const PIXIE_REPO = "pixie:";

interface Props {
  // With `compose`, the chat opens with its message field focused.
  onOpenChat: (sessionId: string, compose?: boolean) => void;
  onOpenPixie: (id: string) => void;
}

/**
 * Every approval, question, review, merge, failed check and stuck chat by project, and
 * pixies' unread warn and action reports under the pixie.
 */
export function Inbox({ onOpenChat, onOpenPixie }: Props) {
  const { state } = useStore();
  const heading = (repo: string) => {
    if (!repo.startsWith(PIXIE_REPO)) {
      return (
        <>
          <ProjectIcon name={repo} />
          <span>{repo}</span>
        </>
      );
    }
    const pixie = state.pixies[repo.slice(PIXIE_REPO.length)];
    // A pixie deleted meanwhile.
    if (pixie === undefined) return <span>Pixie</span>;
    return (
      <>
        <Sprite mascot={pixie.mascot} color={pixie.color} size={22} />
        <span>{pixie.name}</span>
        <button
          className="pxopen"
          aria-label={`Open ${pixie.name}`}
          onClick={() => {
            onOpenPixie(pixie.id);
          }}
        >
          <Icon name="chevr" />
        </button>
      </>
    );
  };
  const groups = inboxGroups(state);
  return (
    <>
      <div className="navr" />
      <h1 className="lt">Inbox</h1>
      {groups.length === 0 && (
        <div className="allclear gl">
          <Icon name="check" />
          <b>All clear</b>
          <span>Nothing needs you.</span>
        </div>
      )}
      {groups.map((group) => (
        <section key={group.repo} aria-labelledby={`inbox-${group.repo}`}>
          <h2 className="pg-h" id={`inbox-${group.repo}`}>
            {heading(group.repo)}
            <span className="gc">
              {group.items.length +
                group.failures.length +
                group.stuck.length +
                group.reports.length}
            </span>
          </h2>
          {group.items.map((approval) => (
            <InboxCard key={approval.id} approval={approval} onOpenChat={onOpenChat} />
          ))}
          {group.failures.map((failure) => (
            <CiFailureCard key={failure.session.id} failure={failure} onOpenChat={onOpenChat} />
          ))}
          {group.reports.map((report) => (
            <ReportCard key={report.id} report={report} onOpenPixie={onOpenPixie} />
          ))}
          {group.stuck.map(({ session, stuck }) => (
            <StuckCard
              key={`stuck-${session.id}`}
              session={session}
              stuck={stuck}
              onOpenChat={onOpenChat}
            />
          ))}
        </section>
      ))}
    </>
  );
}
