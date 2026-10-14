import { useState } from "react";
import type { PixieReport } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Card } from "../approvals/SwipeCard.tsx";
import { SEVERITIES } from "../pixies/habits.ts";
import { Sprite } from "../pixies/Sprite.tsx";

/**
 * An unread warn or action report (B42). Open goes to the pixie, which reads its reports;
 * Dismiss marks this one read.
 */
export function ReportCard({
  report,
  onOpenPixie,
}: {
  report: PixieReport;
  onOpenPixie: (id: string) => void;
}) {
  const { state, actions } = useStore();
  const [busy, setBusy] = useState(false);
  const pixie = state.pixies[report.pixie_id];
  const dismiss = async () => {
    setBusy(true);
    await actions.readReport(report.id);
    setBusy(false);
  };
  return (
    <Card label={`Report: ${report.title}`}>
      <div className={`ck-k sev-${report.severity}`}>
        {pixie !== undefined && <Sprite mascot={pixie.mascot} color={pixie.color} size={16} />}
        <span>{pixie?.name ?? "A pixie"}</span>
        <span className="pxsev">{SEVERITIES[report.severity]}</span>
      </div>
      <div className="cq">{report.title}</div>
      {report.body !== "" && <div className="pxrb">{report.body}</div>}
      <div className="acts">
        <button className="b qb2" disabled={busy} onClick={() => void dismiss()}>
          Dismiss
        </button>
        <button
          className="b b-pri"
          onClick={() => {
            onOpenPixie(report.pixie_id);
          }}
        >
          Open
        </button>
      </div>
    </Card>
  );
}
