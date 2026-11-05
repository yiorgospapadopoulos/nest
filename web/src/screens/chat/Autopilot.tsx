import { useId, useState } from "react";
import type { AutopilotDecision, AutopilotReport } from "../../api/types.ts";
import { decisionAnswer, decisionOpens, decisionReason } from "../../transcript/decisions.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Markdown } from "../../ui/Markdown.tsx";
import { Sheet } from "../../ui/Sheet.tsx";
import {
  DECIDED,
  ENDED,
  HOURS,
  STOP_AFTER,
  WEEKLY_CAPS,
  type AutopilotControl,
} from "./useAutopilot.ts";
import type { Option } from "./options.ts";

/** One choice of a few, the plan card's segments. */
function Choices<T extends string>({
  label,
  shown = label,
  options,
  value,
  onPick,
}: {
  label: string;
  // Its heading; none where the line above says it.
  shown?: string | null;
  options: Option<T>[];
  value: string;
  onPick: (value: T) => void;
}) {
  const id = useId();
  return (
    <>
      {shown !== null && (
        <h3 id={id} className="lbl">
          {shown}
        </h3>
      )}
      <div
        className="pmodes"
        role="radiogroup"
        {...(shown === null ? { "aria-label": label } : { "aria-labelledby": id })}
      >
        {options.map((option) => (
          <button
            key={option.value}
            role="radio"
            aria-checked={option.value === value}
            onClick={() => {
              onPick(option.value);
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
    </>
  );
}

/** The red infinity beside the mic; it opens the switch and what may stop the run early. */
export function AutopilotButton({
  control,
  disabled,
}: {
  control: AutopilotControl;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className={control.on ? "qb ap" : "qb"}
        aria-label={`Autopilot: ${control.on ? "on" : "off"}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Autopilot"
        disabled={disabled}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Icon name="infinity" />
      </button>
      {open && (
        <Sheet
          title="Autopilot"
          onClose={() => {
            setOpen(false);
          }}
          trailing={
            <button
              className="sw ap"
              role="switch"
              aria-checked={control.on}
              aria-label="Autopilot"
              onClick={() => {
                control.setOn(!control.on);
              }}
            />
          }
        >
          <div className="apop">
            <Choices
              label="Stop after"
              options={STOP_AFTER}
              value={control.stopAfter}
              onPick={control.setStopAfter}
            />
            {control.stopAfter === "time" && (
              <Choices
                label="How long"
                shown={null}
                options={HOURS}
                value={control.minutes}
                onPick={control.setMinutes}
              />
            )}
            <Choices
              label="Weekly usage cap"
              options={WEEKLY_CAPS}
              value={control.cap}
              onPick={control.setCap}
            />
          </div>
        </Sheet>
      )}
    </>
  );
}

function DecisionBody({ decision }: { decision: AutopilotDecision }) {
  const reason = decisionReason(decision);
  return (
    <div className="m-decb">
      {decision.options.length > 0 && (
        <ul>
          {decision.options.map((option, index) => (
            <li key={index} className={option.picked ? "on" : undefined}>
              {option.picked && <Icon name="check" />}
              <span>
                <b>{option.label}</b>
                {option.description !== null && <span>{option.description}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {decision.detail !== null && <Markdown text={decision.detail} />}
      {reason !== null && <p>{reason}</p>}
    </div>
  );
}

/**
 * One decision: the small red infinity, what was asked and the answer in red; it opens to
 * the options and the reason, or to a plan's text.
 */
export function DecisionLine({
  decision,
  ev,
}: {
  decision: AutopilotDecision;
  ev?: string | undefined;
}) {
  const line = (
    <>
      <Icon name="infinity" />
      <span>
        {decision.title}{" "}
        <b>
          {decision.kind === "denied" && <Icon name="x" />}
          {decisionAnswer(decision)}
        </b>
      </span>
    </>
  );
  if (!decisionOpens(decision)) {
    return (
      <div className="m-dec" data-ev={ev}>
        <div className="m-decl">{line}</div>
      </div>
    );
  }
  return (
    <details className="m-dec" data-ev={ev}>
      <summary className="m-decl">
        {line}
        <Icon name="chev" className="cv" />
      </summary>
      <DecisionBody decision={decision} />
    </details>
  );
}

/** How a run ended and what it decided, where it ended in the chat. */
export function AutopilotReportCard({
  report,
  ev,
}: {
  report: AutopilotReport;
  ev: string | undefined;
}) {
  return (
    <div className="apr" role="group" aria-label="Autopilot report" data-ev={ev}>
      <div className="apr-h">
        <Icon name="infinity" />
        <b>{ENDED[report.ended]}</b>
      </div>
      {report.summary !== null && <Markdown text={report.summary} />}
      {report.decisions.length > 0 && (
        <>
          <h3 className="lbl">{DECIDED}</h3>
          <ul aria-label={DECIDED}>
            {report.decisions.map((decision, index) => (
              <li key={index}>
                <DecisionLine decision={decision} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
