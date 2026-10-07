import { useStore } from "../../store/context.ts";
import { inboxGroups } from "../../store/selectors.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { InboxCard } from "./InboxCard.tsx";
import { CiFailureCard } from "./PrCards.tsx";
import { StuckCard } from "./StuckCard.tsx";

/** Every approval, question, review, merge, failed check and stuck chat, by project. */
export function Inbox({ onOpenChat }: { onOpenChat: (sessionId: string) => void }) {
  const { state } = useStore();
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
            <ProjectIcon name={group.repo} />
            <span>{group.repo}</span>
            <span className="gc">
              {group.items.length + group.failures.length + group.stuck.length}
            </span>
          </h2>
          {group.items.map((approval) => (
            <InboxCard key={approval.id} approval={approval} onOpenChat={onOpenChat} />
          ))}
          {group.failures.map((failure) => (
            <CiFailureCard key={failure.session.id} failure={failure} onOpenChat={onOpenChat} />
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
