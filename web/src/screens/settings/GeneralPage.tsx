import { useEffect, useState } from "react";
import type { StorageUsage, StoredAttachment } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { Loading, Row, Section, SelectRow, type Choice } from "./rows.tsx";

type Phase = "idle" | "confirm" | "restarting" | "failed";

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

/** Storage and Nest itself: the version and Restart (B81). */
export function GeneralPage() {
  return (
    <>
      <StorageSection />
      <NestSection />
    </>
  );
}

function StorageSection() {
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

  if (settings === null) return <Loading title="Storage" />;
  const parts =
    usage === null
      ? []
      : [
          { label: "chats", bytes: usage.chats_bytes, tone: "run" },
          { label: "attachments", bytes: usage.attachments_bytes, tone: "wait" },
          { label: "artifacts", bytes: usage.artifacts_bytes, tone: "rev" },
        ];
  return (
    <Section title="Storage">
      <div className="srow">
        <span className="slab">Space used</span>
        {usage === null ? (
          <span className="sval">...</span>
        ) : (
          <div className="sused">
            <div
              className="sbar"
              role="img"
              aria-label={parts.map((p) => `${p.label} ${sizeText(p.bytes)}`).join(", ")}
            >
              {parts.map((p) => (
                <i
                  key={p.label}
                  className={`s-${p.tone}`}
                  style={{
                    width: `${String((p.bytes / Math.max(1, usage.total_bytes)) * 100)}%`,
                  }}
                />
              ))}
            </div>
            <span className="sval">{sizeText(usage.total_bytes)}</span>
          </div>
        )}
      </div>
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

/** The version, and Restart: the daemon restarts, then the page loads again. */
function NestSection() {
  const { actions } = useStore();
  const [version, setVersion] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const restarting = phase === "restarting";

  useEffect(() => {
    let live = true;
    void actions.version().then((found) => {
      if (live) setVersion(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const restart = async () => {
    setPhase("restarting");
    const result = await actions.restartService();
    if (result === "back") window.location.reload();
    else setPhase(result === null ? "idle" : "failed");
  };

  return (
    <Section title="Nest">
      <Row label="Version">
        <span className="sval mono">{version ?? "..."}</span>
      </Row>
      <Row label="Restart Nest">
        <button
          className="b"
          disabled={restarting}
          onClick={() => {
            setPhase("confirm");
          }}
        >
          {restarting ? "Restarting..." : "Restart"}
        </button>
      </Row>
      {phase === "failed" && (
        <p className="srow note" role="alert">
          Nest did not come back. Check that the Mac is awake, then reload.
        </p>
      )}
      {phase === "confirm" && (
        <Confirm
          title="Restart Nest?"
          about="Running turns are interrupted. They can be resumed after the restart."
          action="Restart"
          onConfirm={() => void restart()}
          onClose={() => {
            setPhase("idle");
          }}
        />
      )}
    </Section>
  );
}
