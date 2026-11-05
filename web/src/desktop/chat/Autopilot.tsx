// Autopilot on a pane (B120): its button in the composer's row with a small popover, and the
// report a run leaves in the chat.
import { useRef, useState } from "react";
import type { AutopilotDecision, AutopilotReport } from "../../api/types.ts";
import {
  DECIDED,
  ENDED,
  HOURS,
  STOP_AFTER,
  WEEKLY_CAPS,
  type AutopilotControl,
} from "../../screens/chat/useAutopilot.ts";
import { decisionAnswer, decisionOpens, decisionReason } from "../../transcript/decisions.ts";
import { Markdown } from "../../ui/Markdown.tsx";
import { Segmented, Toggle } from "../ui/controls.tsx";
import { Popover } from "../ui/Popover.tsx";
import { useOpen } from "./expanded.ts";
import { Disclosure, Glyph } from "./glyphs.tsx";

export function AutopilotButton({
  control,
  disabled,
}: {
  control: AutopilotControl;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={anchor}
        className={control.on ? "dk-btn k-plain icon dc-apb on" : "dk-btn k-plain icon dc-apb"}
        title="Autopilot"
        aria-label={`Autopilot: ${control.on ? "on" : "off"}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Glyph name="infinity" size={14} />
      </button>
      {open && (
        <Popover
          anchor={anchor}
          label="Autopilot"
          side="above"
          align="start"
          className="dc-apop"
          onClose={() => {
            setOpen(false);
          }}
        >
          <div className="dc-apop-on">
            <b>Autopilot</b>
            <Toggle label="Autopilot" checked={control.on} onChange={control.setOn} />
          </div>
          <span className="dc-label">Stop after</span>
          <Segmented
            label="Stop after"
            value={control.stopAfter}
            options={STOP_AFTER}
            onChange={control.setStopAfter}
          />
          {control.stopAfter === "time" && (
            <Segmented
              label="How long"
              value={control.minutes}
              options={HOURS}
              onChange={control.setMinutes}
            />
          )}
          <span className="dc-label">Weekly usage cap</span>
          <Segmented
            label="Weekly usage cap"
            value={control.cap}
            options={WEEKLY_CAPS}
            onChange={control.setCap}
          />
        </Popover>
      )}
    </>
  );
}

/**
 * One decision: the small red infinity, what was asked and the answer in red; it opens to
 * the options and the reason, or to a plan's text.
 */
export function DecisionLine({
  decision,
  chat,
  id,
  ev,
}: {
  decision: AutopilotDecision;
  chat: string;
  // Its row's name in `chat`, which keeps it open as the transcript redraws.
  id: string;
  ev?: string;
}) {
  const [flipped, toggle] = useOpen(chat, id);
  const opens = decisionOpens(decision);
  const open = opens && flipped;
  const reason = decisionReason(decision);
  return (
    <div className="dc-dec" data-ev={ev}>
      <button
        className="dc-line"
        disabled={!opens}
        aria-expanded={opens ? open : undefined}
        onClick={toggle}
      >
        <Glyph name="infinity" size={11} className="dc-deci" />
        <span className="dc-dect">
          {decision.title}{" "}
          <b>
            {decision.kind === "denied" && <Glyph name="close" size={8} />}
            {decisionAnswer(decision)}
          </b>
        </span>
        {opens && <Disclosure open={open} />}
      </button>
      {open && (
        <div className="dc-decb">
          {decision.options.length > 0 && (
            <ul>
              {decision.options.map((option, index) => (
                <li key={index} className={option.picked ? "on" : undefined}>
                  {option.picked && <Glyph name="check" size={10} />}
                  <b>{option.label}</b>
                  {option.description !== null && <span>{option.description}</span>}
                </li>
              ))}
            </ul>
          )}
          {decision.detail !== null && (
            <div className="dc-md">
              <Markdown text={decision.detail} />
            </div>
          )}
          {reason !== null && <p>{reason}</p>}
        </div>
      )}
    </div>
  );
}

/** How a run ended and what it decided, where it ended in the chat. */
export function AutopilotReportCard({
  report,
  chat,
  id,
  ev,
}: {
  report: AutopilotReport;
  chat: string;
  id: string;
  ev?: string;
}) {
  return (
    <div className="dc-apr" role="group" aria-label="Autopilot report" data-ev={ev}>
      <div className="dc-apr-h">
        <Glyph name="infinity" size={13} className="dc-bad" />
        <b>{ENDED[report.ended]}</b>
      </div>
      {report.summary !== null && (
        <div className="dc-md">
          <Markdown text={report.summary} />
        </div>
      )}
      {report.decisions.length > 0 && (
        <>
          <span className="dc-label">{DECIDED}</span>
          <ul aria-label={DECIDED}>
            {report.decisions.map((decision, index) => (
              <li key={index}>
                <DecisionLine decision={decision} chat={chat} id={`${id}.${String(index)}`} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
