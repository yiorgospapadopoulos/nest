import type { SetupReport } from "../../../api/types.ts";
import { useBridge } from "../../context.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { useCopy } from "../../setup/useCopy.ts";
import { Button } from "../../ui/controls.tsx";
import { shortPath, useOpenPath } from "../config/util.ts";

/** The report in full, before anything else: Nest sends nothing, the file is the user's. */
export function BugReportSheet({ report, onClose }: { report: SetupReport; onClose: () => void }) {
  const open = useOpenPath();
  const bridge = useBridge();
  const { copied, copy } = useCopy(report.text);
  // The issue opens in the browser for the user to read and submit; too long a report is
  // attached by hand, so its file shows too.
  const reportOnGitHub = () => {
    void bridge.openExternal(report.issue_url);
    if (report.attach_file) open?.(report.path, true);
  };
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
          <Button kind="primary" size="large" onClick={reportOnGitHub}>
            Report on GitHub
          </Button>
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
