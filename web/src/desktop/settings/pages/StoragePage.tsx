import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { StorageUsage, StoredAttachment } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Button } from "../../ui/controls.tsx";
import { Alert } from "../../sheets/Alert.tsx";
import { choiceItems } from "../parts1/choices.ts";
import { Dropdown } from "../rows.tsx";
import {
  ARCHIVE_CHOICES,
  archiveLabel,
  attachmentSource,
  bytes,
  ledger,
  PART_NAMES,
  segments,
  shares,
} from "../parts1/words.ts";
import { SettingsListRow, SettingsRow, SettingsSection, Value } from "../rows.tsx";
import "../parts1/parts1.css";

/** The Mac's Storage (B86): the space used, archiving, clean up and the search index. */
export function StoragePage() {
  const { state, actions } = useStore();
  const settings = state.settings.storage;
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  // The largest attachments while Clean up lists them.
  const [attachments, setAttachments] = useState<StoredAttachment[] | null>(null);
  const [deleting, setDeleting] = useState<StoredAttachment | null>(null);
  const [busy, setBusy] = useState<string[]>([]);
  const [rebuilding, setRebuilding] = useState(false);

  useEffect(() => {
    let live = true;
    void actions.storage().then((found) => {
      if (live) setUsage(found);
    });
    return () => {
      live = false;
    };
  }, [actions]);

  const review = async () => {
    const found = await actions.largeAttachments();
    if (found !== null) setAttachments(found);
  };

  const remove = async (attachment: StoredAttachment) => {
    setBusy((ids) => [...ids, attachment.id]);
    const done = await actions.deleteAttachment(attachment);
    setBusy((ids) => ids.filter((id) => id !== attachment.id));
    if (done) setAttachments((list) => list?.filter((a) => a.id !== attachment.id) ?? null);
  };

  const rebuild = async () => {
    setRebuilding(true);
    await actions.rebuildSearch();
    setRebuilding(false);
  };

  return (
    <SettingsSection bare>
      {usage === null ? (
        <div className="dks-rows">
          <SettingsRow label="Space used">
            <Value text="-" />
          </SettingsRow>
        </div>
      ) : (
        <Ledger usage={usage} />
      )}
      <SettingsRow label="Archive chats idle for">
        <Dropdown
          label="Archive chats idle for"
          title={archiveLabel(settings?.archive_after_days ?? null)}
          width={110}
          disabled={settings === null}
          items={() =>
            choiceItems(
              ARCHIVE_CHOICES,
              settings?.archive_after_days ?? null,
              archiveLabel,
              (days) => {
                if (settings !== null) {
                  void actions.saveSection("storage", { archive_after_days: days }, settings);
                }
              },
            )
          }
        />
      </SettingsRow>
      <SettingsRow label="Clean up">
        {attachments === null ? (
          <Button onClick={() => void review()}>Review large attachments…</Button>
        ) : (
          <Button
            onClick={() => {
              setAttachments(null);
            }}
          >
            Done
          </Button>
        )}
      </SettingsRow>
      {attachments !== null && (
        <div className="dks-attach">
          {attachments.length === 0 && <p className="dks-attachnone">No attachments</p>}
          {attachments.map((attachment) => (
            <SettingsListRow
              key={attachment.id}
              title={attachment.name}
              detail={`${bytes(attachment.bytes)} · ${attachmentSource(attachment)}`}
              leading={<FileBadge image={attachment.media_type.startsWith("image")} />}
              trailing={
                <Button
                  kind="danger"
                  aria-label={`Delete ${attachment.name}`}
                  disabled={busy.includes(attachment.id)}
                  onClick={() => {
                    setDeleting(attachment);
                  }}
                >
                  Delete
                </Button>
              }
            />
          ))}
        </div>
      )}
      <SettingsRow label="Search index">
        {rebuilding && <Fireflies />}
        <Button disabled={rebuilding} onClick={() => void rebuild()}>
          Rebuild
        </Button>
      </SettingsRow>
      {deleting !== null && (
        <Alert
          title={`Delete ${deleting.name}?`}
          message="It is deleted for good. Its chat shows that it is gone."
          actions={[
            { title: "Delete", kind: "destructive", onSelect: () => void remove(deleting) },
          ]}
          onClose={() => {
            setDeleting(null);
          }}
        />
      )}
    </SettingsSection>
  );
}

/** The space used (B86): the total, a bar of the parts, and one line per part. */
function Ledger({ usage }: { usage: StorageUsage }) {
  return (
    <div className="dks-ledger">
      <div className="dks-ledgert">
        <b>{bytes(usage.total_bytes)}</b>
        <span>used by Nest</span>
      </div>
      <StorageBar usage={usage} />
      <div className="dks-ledgerl">
        {ledger(usage).map(({ part, size, share }) => (
          <div key={part} className="dks-ledgerr">
            <i className={`p-${part}`} />
            <span>{PART_NAMES[part]}</span>
            <span>{size}</span>
            <span className="dks-ledgers">{share}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The attachment's square badge: a photo or a document, as SettingsBadge. */
function FileBadge({ image }: { image: boolean }) {
  return (
    <span className="dks-badge" aria-hidden="true">
      <svg className="ic" viewBox="0 0 24 24">
        {image ? (
          <>
            <rect x="3.5" y="5" width="17" height="14" rx="2" />
            <path d="M3.5 16l5-5 4 4 3-3 5 5" />
            <circle cx="15.5" cy="9.5" r="1.3" />
          </>
        ) : (
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5" />
        )}
      </svg>
    </span>
  );
}

/** The parts side by side across the width, 2 px apart, tiny ones kept visible. */
function StorageBar({ usage }: { usage: StorageUsage }) {
  const bar = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = bar.current;
    if (element === null) return;
    const observer = new ResizeObserver(() => {
      setWidth(element.clientWidth);
    });
    observer.observe(element);
    setWidth(element.clientWidth);
    return () => {
      observer.disconnect();
    };
  }, []);
  return (
    <div ref={bar} className="dks-sbar" aria-hidden="true">
      {width > 0 &&
        segments(shares(usage), width, 2, 3).map(({ part, width: w }) => (
          <i key={part} className={`p-${part}`} style={{ width: w }} />
        ))}
    </div>
  );
}
