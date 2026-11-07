import type { SetupReport } from "../../../api/types.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { useCopy } from "../../setup/useCopy.ts";
import { Button } from "../../ui/controls.tsx";
import { shortPath, useOpenPath } from "../config/util.ts";

/** The report in full, before anything else: Nest sends nothing, the file is the user's. */
export function BugReportSheet({ report, onClose }: { report: SetupReport; onClose: () => void }) {
  const open = useOpenPath();
  const { copied, copy } = useCopy(report.text);
  return (
    <SheetFrame
      title="Bug report"
      onClose={onClose}
      width={680}
      footer={
        <>
          <Button size="large" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </Button>
          {open !== null && (
            <Button
              size="large"
              onClick={() => {
                open(report.path, true);
              }}
            >
              Show the file
            </Button>
          )}
        </>
      }
    >
      <p className="su-line">{`Nest sends nothing. Saved as ${shortPath(report.path)}`}</p>
      <pre className="su-report" tabIndex={0}>
        {report.text}
      </pre>
    </SheetFrame>
  );
}
