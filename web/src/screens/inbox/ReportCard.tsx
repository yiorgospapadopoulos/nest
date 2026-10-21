import { useState } from "react";
import type { PixieReport } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { SEVERITIES } from "../pixies/habits.ts";
import { FoldRow } from "./FoldRow.tsx";

/**
 * An unread warn or action report (B42), as a row naming its pixie (B102). Open goes to
 * the pixie, which reads its reports; Dismiss marks this one read.
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
  const open = () => {
    onOpenPixie(report.pixie_id);
  };
  const dismiss = async () => {
    setBusy(true);
    await actions.readReport(report.id);
    setBusy(false);
  };
  return (
    <FoldRow
      label={`Report: ${report.title}`}
      tone={report.severity === "action" ? "fail" : "wait"}
      name={pixie?.name ?? "A pixie"}
      onOpen={open}
      line={`${SEVERITIES[report.severity]} · ${report.title}`}
    >
      {report.body !== "" && <div className="pxrb">{report.body}</div>}
      <div className="acts">
        <button className="b b-pri" onClick={open}>
          Open
        </button>
        <button className="b qb2" disabled={busy} onClick={() => void dismiss()}>
          Dismiss
        </button>
      </div>
    </FoldRow>
  );
}
