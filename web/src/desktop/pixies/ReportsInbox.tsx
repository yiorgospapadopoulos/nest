import type { PixieReport } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { unreadActions, unreadReports } from "../../store/selectors.ts";
import { useShell } from "../shell/context.ts";
import { Button } from "../ui/controls.tsx";
import { CountBadge, StatusDot } from "./bits.tsx";
import { useNow } from "./useNow.ts";
import { clockTime } from "./habitText.ts";
import { Sprite } from "./Sprite.tsx";

const TONE = { info: "done", warn: "wait", action: "fail" } as const;
const SEVERITY = { info: "Info", warn: "Warning", action: "Needs action" } as const;

/**
 * The pixies' unread warnings and actions at the top of the Pixies list (B42), newest
 * first: the pixie, the report's title, Open (the pixie, its reports read) and Dismiss.
 * Nothing while there are none.
 */
export function ReportsInbox() {
  const { state } = useStore();
  const inbox = unreadReports(state);
  if (inbox.length === 0) return null;
  return (
    <section className="px-inbox" aria-label="Reports">
      <h2 className="px-inbox-h">
        Reports
        <CountBadge count={inbox.length} urgent={unreadActions(state) > 0} />
      </h2>
      {inbox.map((report) => (
        <ReportEntry key={report.id} report={report} />
      ))}
    </section>
  );
}

function ReportEntry({ report }: { report: PixieReport }) {
  const { state, actions } = useStore();
  const shell = useShell();
  const now = useNow();
  const pixie = state.pixies[report.pixie_id];
  const open = () => {
    shell.openPixie(report.pixie_id);
    const unread = Object.values(state.reports)
      .filter((r) => r.pixie_id === report.pixie_id && r.read_at === null)
      .map((r) => r.id);
    void actions.readPixieReports(report.pixie_id, unread);
  };
  return (
    <article
      className="px-report"
      aria-label={`${SEVERITY[report.severity]} from ${pixie?.name ?? "a pixie"}: ${report.title}`}
    >
      <div className="px-report-by">
        <StatusDot tone={TONE[report.severity]} />
        {pixie !== undefined && <Sprite mascot={pixie.mascot} color={pixie.color} size={12} />}
        <span className="px-report-name">{pixie?.name ?? "A pixie"}</span>
        <span className="px-report-at">{clockTime(report.created_at, now)}</span>
      </div>
      <p className="px-report-title">{report.title}</p>
      <div className="px-report-acts">
        <Button
          kind="soft"
          title={`Open ${pixie?.name ?? "the pixie"} and mark its reports read`}
          onClick={open}
        >
          Open
        </Button>
        <Button
          kind="plain"
          title="Mark this report read"
          onClick={() => void actions.readReport(report.id)}
        >
          Dismiss
        </Button>
      </div>
    </article>
  );
}
