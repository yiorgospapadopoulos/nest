import type { EarlierWorktree } from "../../api/types.ts";
import { Icon } from "../../ui/Icon.tsx";
import { earlierName, nameEnds } from "./earlier.ts";

interface ToggleProps {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
}

/** The count at a chat row's right end; it sits outside the row's own button. */
export function EarlierToggle({ title, count, open, onToggle }: ToggleProps) {
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

/** The chat's earlier worktrees beneath its row, each name shortened in the middle. */
export function EarlierList({ worktrees }: { worktrees: EarlierWorktree[] }) {
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
