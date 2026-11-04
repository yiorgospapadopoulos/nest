import type { EarlierWorktree } from "../../../api/types.ts";
import { earlierName, nameEnds } from "../../../screens/chat/earlier.ts";
import { Icon } from "../../../ui/Icon.tsx";

interface CountProps {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
}

/** The count at a chat row's right end, as the Mac's EarlierCount (B119). */
export function EarlierCount({ title, count, open, onToggle }: CountProps) {
  const label = `Earlier worktrees of ${title}`;
  return (
    <button
      className="ewt"
      aria-expanded={open}
      aria-label={label}
      title={label}
      onClick={onToggle}
    >
      <Icon name="chevr" />
      {count}
    </button>
  );
}

/** A chat's earlier worktrees beneath its row, as the Mac's EarlierWorktreesList. */
export function EarlierWorktreesList({ worktrees }: { worktrees: EarlierWorktree[] }) {
  return (
    <ul className="ewl">
      {worktrees.map((worktree) => {
        const name = earlierName(worktree);
        const [start, end] = nameEnds(name);
        return (
          <li key={`${worktree.path}-${worktree.started_at}`}>
            <span className="ewn" title={name}>
              <span>{start}</span>
              <span>{end}</span>
            </span>
            <span>{worktree.state}</span>
          </li>
        );
      })}
    </ul>
  );
}
