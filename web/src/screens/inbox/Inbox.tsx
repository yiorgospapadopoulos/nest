import { useStore } from "../../store/context.ts";
import { inboxGroups, needsCount } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { GoalsSection } from "./GoalsSection.tsx";
import { InboxCard } from "./InboxCard.tsx";
import { CiFailureCard } from "./PrCards.tsx";
import { ReportCard } from "./ReportCard.tsx";
import { StuckCard } from "./StuckCard.tsx";

// A pixie chat's repo; its items are grouped under the pixie (D072).
const PIXIE_REPO = "pixie:";

interface Props {
  // The project the Chats tab shows, whose goals show under Needs you.
  project: string | null;
  onOpenChat: (sessionId: string) => void;
  onOpenPixie: (id: string) => void;
}

/**
 * The Needs you tab, as the Mac's right panel (B102 items 10, 11): every approval,
 * question, review, merge, failed check and stuck chat by project, and pixies' unread warn
 * and action reports under the pixie, one short row each; then the project's goals.
 */
export function Inbox({ project, onOpenChat, onOpenPixie }: Props) {
  const { state } = useStore();
  const heading = (repo: string) => {
    if (!repo.startsWith(PIXIE_REPO)) return <span>{repo}</span>;
    const pixie = state.pixies[repo.slice(PIXIE_REPO.length)];
    // A pixie deleted meanwhile.
    if (pixie === undefined) return <span>Pixie</span>;
    return (
      <>
        <Sprite mascot={pixie.mascot} color={pixie.color} size={14} />
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
  const count = needsCount(state);
  return (
    <>
      <header className="bar">
        <h1 className="bar-t">Needs you</h1>
        {count > 0 && <span className="bar-n">{count}</span>}
      </header>
      {groups.length === 0 && (
        <p className="allclear">
          <Icon name="check" />
          Nothing needs you.
        </p>
      )}
      {groups.map((group) => (
        <section key={group.repo} aria-labelledby={`inbox-${group.repo}`}>
          <h2 className="lbl" id={`inbox-${group.repo}`}>
            {heading(group.repo)}
            <span className="c">
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
      {project !== null && <GoalsSection project={project} onOpenChat={onOpenChat} />}
    </>
  );
}
