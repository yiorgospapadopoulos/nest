import type { ReactNode } from "react";
import { useStore } from "../../store/context.ts";
import { goalEntries, inboxGroups } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import type { RightCard } from "../layout/project.ts";
import { RIGHT_PANEL_WIDTH } from "../layout/sidebar.ts";
import { useShell } from "./context.ts";
import { GoalsCard, NeedsCard } from "./frame/Activity.tsx";
import "./frame/frame.css";

// The squeezed panel's strip, with its accent line down the middle (RightPanel.railWidth).
const RAIL = 6;

/**
 * The activity panel, as the Mac's RightPanel: Needs you and Goals cards sharing its
 * height, each folding to its header. Squeezed, it is an accent hairline that opens it.
 */
export function RightPanel() {
  const { state } = useStore();
  const shell = useShell();
  const project = shell.repo.name;
  const group = inboxGroups(state).find((g) => g.repo === project);
  const needs =
    group === undefined ? 0 : group.items.length + group.failures.length + group.stuck.length;
  if (shell.state.rightCollapsed) {
    return (
      <button
        className="fr-rrail"
        style={{ width: RAIL }}
        title="Open details"
        aria-label={needs > 0 ? `Open details, ${String(needs)} need you` : "Open details"}
        onClick={shell.toggleActivity}
      >
        <i />
      </button>
    );
  }
  const goals = goalEntries(state, project).length;
  const open = shell.state.openCards;
  return (
    <aside className="dk-right fr-right" style={{ width: RIGHT_PANEL_WIDTH }} aria-label="Activity">
      <Card
        id="needsYou"
        title="Needs you"
        count={needs}
        urgent={needs > 0}
        open={open.has("needsYou")}
      >
        <NeedsCard project={project} />
      </Card>
      <Card id="goals" title="Goals" count={goals} open={open.has("goals")}>
        <GoalsCard project={project} />
      </Card>
    </aside>
  );
}

interface CardProps {
  id: RightCard;
  title: string;
  count: number;
  urgent?: boolean;
  open: boolean;
  children: ReactNode;
}

function Card({ id, title, count, urgent = false, open, children }: CardProps) {
  const shell = useShell();
  return (
    <section className={`fr-pcard${open ? " open" : ""}`} aria-label={title}>
      <button
        className="fr-pch"
        aria-expanded={open}
        aria-label={`${title}, ${String(count)}`}
        onClick={() => {
          shell.update((s) => {
            s.toggleCard(id);
          });
        }}
      >
        {title}
        <span className={urgent ? "fr-count urgent" : "fr-count"}>{count}</span>
        <Icon name="chev" className="fr-pcv" />
      </button>
      {open && <div className="fr-pcb">{children}</div>}
    </section>
  );
}
