import { useEffect, useRef, useState, type PointerEvent } from "react";
import type { UsageSettings } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { meterEntries, movedTo } from "../../../store/usageMeter.ts";
import { EngineMark } from "../../shell/frame/marks.tsx";
import { UsagePanel } from "../../shell/frame/UsagePanel.tsx";
import { Toggle } from "../../ui/controls.tsx";
import { choiceItems } from "../parts1/choices.ts";
import { Dropdown } from "../rows.tsx";
import {
  dragOffset,
  dragTarget,
  movedBy,
  REFRESH_CHOICES,
  refreshInterval,
  WARN_CHOICES,
  warnLevel,
} from "../parts1/words.ts";
import { CheckBox, SettingsRow, SettingsSection } from "../rows.tsx";
import "../parts1/parts1.css";

/** The Mac's Usage (B86): the usage panel at the page's width, then the usage settings. */
export function UsagePage() {
  const { state } = useStore();
  return (
    <>
      <div className="dks-usage">
        <UsagePanel title="Limits" />
      </div>
      <TopBarSection />
      <UsageLimitsSection settings={state.settings.usage} />
    </>
  );
}

// A press moves its row once the pointer travels this far.
const DRAG_SLOP = 2;

/**
 * Which accounts the usage meter at the top right shows, and in which order, on this
 * device only (B98): a check per account in the user's order; a click on the row toggles it,
 * and its grip, or Alt and the arrow keys, move it.
 */
function TopBarSection() {
  const { state, actions } = useStore();
  const { accounts, usageMeter } = state.settings;
  const entries = accounts === null ? [] : meterEntries(accounts, usageMeter);
  const ids = entries.map((e) => e.id);
  // The row being dragged: where it started, the pointer's start and travel, a row's height.
  const [drag, setDrag] = useState<{
    id: string;
    from: number;
    startY: number;
    dy: number;
    step: number;
  } | null>(null);
  // A drag that just ended swallows the click it would send to its row.
  const dragged = useRef(false);

  useEffect(() => {
    void actions.loadAccounts();
  }, [actions]);

  const to = drag === null ? -1 : dragTarget(drag.from, drag.dy, drag.step, ids.length);

  const onDown = (event: PointerEvent<HTMLSpanElement>, id: string, from: number) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const step = event.currentTarget.closest(".dks-row")?.getBoundingClientRect().height ?? 36;
    setDrag({ id, from, startY: event.clientY, dy: 0, step });
  };
  const onMove = (event: PointerEvent<HTMLSpanElement>) => {
    if (drag !== null) setDrag({ ...drag, dy: event.clientY - drag.startY });
  };
  const onUp = () => {
    if (drag === null) return;
    if (Math.abs(drag.dy) > DRAG_SLOP) {
      dragged.current = true;
      if (to !== drag.from) actions.orderUsageMeter(movedTo(ids, drag.from, to));
    }
    setDrag(null);
  };

  return (
    <SettingsSection title="Top bar shows" hint={{ icon: "lines", text: "Drag to reorder" }}>
      {entries.map((entry, index) => {
        const moving = drag?.id === entry.id;
        const offset =
          drag === null ? 0 : moving ? drag.dy : dragOffset(index, drag.from, to, drag.step);
        return (
          <div
            key={entry.id}
            className={
              moving
                ? "dks-meterrow moving"
                : drag === null
                  ? "dks-meterrow"
                  : "dks-meterrow sliding"
            }
            style={offset === 0 ? undefined : { transform: `translateY(${String(offset)}px)` }}
            role="checkbox"
            tabIndex={0}
            aria-checked={entry.shown}
            aria-label={`Show ${entry.name} in the top bar`}
            aria-description="Alt and the arrow keys move it"
            onClick={() => {
              if (dragged.current) {
                dragged.current = false;
                return;
              }
              actions.setUsageMeterShown(entry.id, !entry.shown, entries);
            }}
            onKeyDown={(event) => {
              if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                actions.setUsageMeterShown(entry.id, !entry.shown, entries);
                return;
              }
              if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
              event.preventDefault();
              actions.orderUsageMeter(movedBy(ids, entry.id, event.key === "ArrowUp" ? -1 : 1));
            }}
          >
            <SettingsRow
              label={entry.name}
              leading={
                <>
                  <span
                    className="dks-grip"
                    aria-hidden="true"
                    onPointerDown={(event) => {
                      onDown(event, entry.id, index);
                    }}
                    onPointerMove={onMove}
                    onPointerUp={onUp}
                    onPointerCancel={onUp}
                  >
                    <svg viewBox="0 0 14 10">
                      <path d="M2 2.5h10M2 5h10M2 7.5h10" />
                    </svg>
                  </span>
                  <EngineMark provider={entry.provider} size={12} />
                </>
              }
            >
              {entry.detail !== "" && <span className="dks-meterd">{entry.detail}</span>}
              <CheckBox on={entry.shown} />
            </SettingsRow>
          </div>
        );
      })}
    </SettingsSection>
  );
}

/** How often the daemon asks for the limits (D031), and the warning before them. */
function UsageLimitsSection({ settings }: { settings: UsageSettings | null }) {
  const { actions } = useStore();
  const save = (change: Partial<UsageSettings>) => {
    if (settings !== null) void actions.saveSection("usage", { ...settings, ...change }, settings);
  };
  const warn = settings?.warn_percent ?? null;
  return (
    <SettingsSection title="Usage limits">
      <SettingsRow label="Check limits">
        <Dropdown
          label="Check limits"
          title={refreshInterval(settings?.refresh_minutes ?? null)}
          disabled={settings === null}
          items={() =>
            choiceItems(
              REFRESH_CHOICES,
              settings?.refresh_minutes ?? 0,
              refreshInterval,
              (refresh_minutes) => {
                save({ refresh_minutes });
              },
            )
          }
        />
      </SettingsRow>
      <SettingsRow label="Warn me at">
        <Dropdown
          label="Warn me at"
          title={settings === null ? "-" : warnLevel(warn)}
          width={100}
          disabled={settings === null}
          items={() =>
            choiceItems(WARN_CHOICES, warn, warnLevel, (warn_percent) => {
              save({ warn_percent });
            })
          }
        />
      </SettingsRow>
      <SettingsRow label="Also as a notification">
        <Toggle
          label="Usage warning as a notification"
          checked={settings?.warn_notify ?? false}
          disabled={settings === null || warn === null}
          onChange={(warn_notify) => {
            save({ warn_notify });
          }}
        />
      </SettingsRow>
    </SettingsSection>
  );
}
