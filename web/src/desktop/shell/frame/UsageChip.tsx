import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../../../store/context.ts";
import { Popover } from "../../ui/Popover.tsx";
import { EngineMark } from "./marks.tsx";
import { meterLines, meterTooltip, type MeterLine, type UsageChip as Chip } from "./usage.ts";
import { useMinute } from "./clock.ts";
import { UsagePanel } from "./UsagePanel.tsx";

/**
 * The tab strip's usage chip, as the Mac's LimitsChip: an engine's mark, a 32 by 4 px bar for
 * its first window and each window as "30% 2h 5m"; with two accounts, a line for each, one
 * above the other. A click opens the usage popover.
 */
export function UsageChip() {
  const { state, actions } = useStore();
  const { accounts, usageMeter } = state.settings;
  const now = useMinute();
  const button = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (accounts === null) void actions.loadAccounts();
  }, [accounts, actions]);

  const cannotRun = useMemo(
    () => new Set((state.providers ?? []).filter((p) => p.state !== "ready").map((p) => p.name)),
    [state.providers],
  );
  const lines = meterLines(accounts ?? [], usageMeter, now, cannotRun);
  const stacked = lines.length > 1;
  const tooltip = stacked
    ? meterTooltip(lines)
    : (lines[0]?.chip?.windows.map((w) => w.tooltip).join(". ") ?? "Usage details");
  return (
    <>
      <button
        ref={button}
        className={stacked ? "fr-uchip stacked" : "fr-uchip"}
        title={tooltip}
        aria-label={`Usage: ${meterTooltip(lines)}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        {stacked ? (
          <span className="fr-ugrid">
            {lines.map((line) => (
              <StackedLine key={line.id} line={line} titled={lines.some((l) => l.title !== null)} />
            ))}
          </span>
        ) : (
          lines[0] !== undefined && <OneLine line={lines[0]} />
        )}
      </button>
      {open && (
        <Popover
          anchor={button}
          label="Usage"
          align="end"
          className="fr-upop"
          onClose={() => {
            setOpen(false);
          }}
        >
          <UsagePanel title="Usage" />
        </Popover>
      )}
    </>
  );
}

function Bar({ chip }: { chip: Chip }) {
  return (
    <span className={`fr-ubar ${chip.tone}`} aria-hidden="true">
      <i style={{ width: `${String(Math.round(chip.used * 100))}%` }} />
    </span>
  );
}

function OneLine({ line }: { line: MeterLine }) {
  return (
    <span className="fr-uline1" aria-hidden="true">
      <EngineMark provider={line.provider} size={12} />
      {line.chip === null ? (
        <span className="fr-udots">···</span>
      ) : (
        <>
          <Bar chip={line.chip} />
          {line.chip.windows.map((w, index) => (
            <Fragment key={index}>
              {index > 0 && <span className="fr-udot">·</span>}
              <span>{w.text}</span>
            </Fragment>
          ))}
        </>
      )}
    </span>
  );
}

/** A row of the stacked chip: mark, title when both are of one engine, bar, two windows. */
function StackedLine({ line, titled }: { line: MeterLine; titled: boolean }) {
  const [short, long] = line.chip?.windows ?? [];
  return (
    <>
      <EngineMark provider={line.provider} size={10} />
      {titled && <span className="fr-utitle">{line.title ?? ""}</span>}
      {line.chip === null ? (
        <span className="fr-udots wide">···</span>
      ) : (
        <>
          <Bar chip={line.chip} />
          <span>{short?.text}</span>
          <span className="fr-udot">{long === undefined ? "" : "·"}</span>
          <span>{long?.text ?? ""}</span>
        </>
      )}
    </>
  );
}
