import { useEffect, useState } from "react";
import type { StorageUsage, StoredAttachment } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { Loading, Row, Section, SelectRow, type Choice } from "./rows.tsx";

// Archive chats idle for this many days; null never (D104).
const ARCHIVE_DAYS = [null, 7, 30, 90];

/** "820 MB", "1.4 GB", "12 KB". */
function sizeText(bytes: number): string {
  let value = bytes;
  for (const unit of ["bytes", "KB", "MB", "GB"]) {
    if (value < 1000) return shown(value, unit);
    value /= 1000;
  }
  return shown(value, "TB");
}

/** Whole numbers, with one decimal below 10 (except bytes). */
function shown(value: number, unit: string): string {
  const rounded = unit === "bytes" || value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${String(rounded)} ${unit}`;
}

function archiveChoices(current: number | null): Choice<number | null>[] {
  const days = ARCHIVE_DAYS.includes(current) ? ARCHIVE_DAYS : [...ARCHIVE_DAYS, current];
  return days.map((d) => ({ value: d, label: d === null ? "Never" : `${String(d)} days` }));
}

/** The space Nest uses and how it is kept small (B81; its own page since B86). */
export function StoragePage() {
  const { state, actions } = useStore();
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const settings = state.settings.storage;

  useEffect(() => {
    let live = true;
    void actions.storage().then((found) => {
      if (live) setUsage(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  if (settings === null) return <Loading />;
  return (
    <Section>
      {usage === null ? (
        <Row label="Space used">
          <span className="sval">...</span>
        </Row>
      ) : (
        <Ledger usage={usage} />
      )}
      <SelectRow
        label="Archive chats idle for"
        value={settings.archive_after_days}
        choices={archiveChoices(settings.archive_after_days)}
        onChange={(days) =>
          void actions.saveSection("storage", { archive_after_days: days }, settings)
        }
      />
      <Row label="Clean up">
        <button
          className="b"
          onClick={() => {
            setReviewing(true);
          }}
        >
          Review large attachments
        </button>
      </Row>
      <Row label="Search index">
        <button className="b" onClick={() => void actions.rebuildSearch()}>
          Rebuild
        </button>
      </Row>
      {reviewing && (
        <LargeAttachments
          onClose={() => {
            setReviewing(false);
          }}
        />
      )}
    </Section>
  );
}

/** A part's whole percent of the total; "<1%" for a part above zero but under 1%. */
function shareText(part: number, total: number): string {
  if (part <= 0 || total <= 0) return "0%";
  const value = (100 * part) / total;
  return value < 1 ? "<1%" : `${String(Math.round(value))}%`;
}

/** The space Nest uses: the total, a bar of its parts, then a line per part (B86). */
function Ledger({ usage }: { usage: StorageUsage }) {
  const parts = [
    { label: "Chats", bytes: usage.chats_bytes, tone: "s-run" },
    { label: "Attachments", bytes: usage.attachments_bytes, tone: "s-wait" },
    { label: "Artifacts", bytes: usage.artifacts_bytes, tone: "s-rev" },
    { label: "Other", bytes: usage.other_bytes, tone: "s-oth" },
  ];
  return (
    <div className="srow ledger">
      <div className="ltotal">
        <b className="ltot">{sizeText(usage.total_bytes)}</b>
        <span className="hint">used by Nest</span>
      </div>
      <div
        className="lbar"
        role="img"
        aria-label={parts.map((p) => `${p.label} ${sizeText(p.bytes)}`).join(", ")}
      >
        {parts
          .filter((p) => p.bytes > 0)
          .map((p) => (
            <i key={p.label} className={p.tone} style={{ flexGrow: p.bytes }} />
          ))}
      </div>
      <div className="llegend">
        {parts.map((p) => (
          <div key={p.label} className="lline">
            <span className={`ldot ${p.tone}`} />
            <span>{p.label}</span>
            <span className="num">{sizeText(p.bytes)}</span>
            <span className="num lpct">{shareText(p.bytes, usage.total_bytes)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The largest attachments, each deleted only after a confirmation. */
function LargeAttachments({ onClose }: { onClose: () => void }) {
  const { actions } = useStore();
  const [items, setItems] = useState<StoredAttachment[] | null>(null);
  const [asking, setAsking] = useState<StoredAttachment | null>(null);
  // Deleted here since the list loaded.
  const [deleted, setDeleted] = useState<string[]>([]);
  const shown = items?.filter((i) => !deleted.includes(i.id)) ?? null;

  useEffect(() => {
    let live = true;
    void actions.largeAttachments().then((found) => {
      if (live) setItems(found ?? []);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  return (
    <Sheet title="Large attachments" onClose={onClose}>
      <div className="lgrp gl">
        {shown === null && <div className="srow note">Loading...</div>}
        {shown?.length === 0 && <div className="srow note">No attachments</div>}
        {shown?.map((item) => (
          <div key={item.id} className="srow">
            <span className="cn">
              <span className="slab">
                {item.name}
                <span className="hint">
                  {sizeText(item.bytes)}
                  {item.session_title !== null && `, ${item.session_title}`}
                </span>
              </span>
            </span>
            <button
              className="b b-no"
              aria-label={`Delete ${item.name}`}
              onClick={() => {
                setAsking(item);
              }}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
      {asking !== null && (
        <Confirm
          title={`Delete ${asking.name}?`}
          about="Its chat shows that it was deleted."
          action="Delete"
          onConfirm={() =>
            void actions.deleteAttachment(asking).then((done) => {
              if (done) setDeleted((before) => [...before, asking.id]);
            })
          }
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
    </Sheet>
  );
}
