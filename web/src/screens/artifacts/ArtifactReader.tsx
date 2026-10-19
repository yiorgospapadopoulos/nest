import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { ApiError } from "../../api/client.ts";
import type {
  Artifact,
  ArtifactAnswer,
  ArtifactContent,
  ArtifactKind,
  ArtifactStorageChange,
} from "../../api/types.ts";
import { activityTime, resetLabel, sizeText } from "../../format.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { useScheme } from "../../appearance/scheme.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import {
  BridgeError,
  PRINT,
  linkMessage,
  storageEvents,
  useArtifactBridge,
  type FileToSave,
  type Handlers,
} from "./bridge.ts";
import { download } from "./files.ts";
import { withCsp } from "./html.ts";
import { KIND_ICONS, KIND_LABELS, originOf } from "./view.ts";

/** A version as read: its content, or null when it could not be read. */
export interface LoadedVersion {
  content: ArtifactContent | null;
}

interface Props {
  artifact: Artifact | undefined;
  version: number;
  // Undefined while it loads.
  loaded: LoadedVersion | undefined;
  onStep: (version: number) => void;
  onRetry: () => void;
}

// Kinds whose page prints itself (B88): their frame may open the print dialog.
const PRINTABLE: ReadonlySet<ArtifactKind> = new Set(["slides", "document"]);

/** One version of an artifact: where it came from, the version stepper and the document. */
export function ArtifactReader({ artifact, ...rest }: Props) {
  if (artifact === undefined) return <p className="note">Loading...</p>;
  return <Reader key={artifact.id} artifact={artifact} {...rest} />;
}

function Reader({ artifact, version, loaded, onStep, onRetry }: Props & { artifact: Artifact }) {
  const { actions } = useStore();
  // The frame shown now: a new version or theme mounts a new one into the same ref.
  const frame = useRef<HTMLIFrameElement>(null);
  const { size, setSize, reread } = useStoredSize(artifact.id);
  const asks = useAsks(artifact.id);
  const [clearing, setClearing] = useState(false);
  const content = loaded?.content;
  const latest = artifact.latest_version;
  const printable = content != null && PRINTABLE.has(content.kind);
  return (
    <div className="afrd">
      <div className="afmeta">
        <span className="afk">
          <Icon name={KIND_ICONS[artifact.kind]} />
          {KIND_LABELS[artifact.kind]}
        </span>
        <span className="afo">{originOf(artifact)}</span>
        {content != null && <span>{activityTime(content.created_at, new Date())}</span>}
        {asks.count !== null && (
          <span>
            {asks.count.limit - asks.count.remaining} of {asks.count.limit} asks today
          </span>
        )}
        {asks.asking && (
          <span className="wline rglow afask" role="status">
            <Fireflies size={9} />
            <span className="glow">Asking Claude...</span>
          </span>
        )}
        {size > 0 && (
          <>
            <span>{sizeText(size)} stored</span>
            <button
              className="lnk afclr"
              onClick={() => {
                setClearing(true);
              }}
            >
              Clear page data
            </button>
          </>
        )}
        {printable && (
          <button
            className="lnk afpdf"
            onClick={() => {
              frame.current?.contentWindow?.postMessage(PRINT, "*");
            }}
          >
            Export PDF
          </button>
        )}
      </div>
      <div className="afst" role="group" aria-label="Versions">
        <button
          className="ib"
          aria-label="Previous version"
          disabled={version <= 1}
          onClick={() => {
            onStep(version - 1);
          }}
        >
          <Icon name="chevl" />
        </button>
        <span>
          Version {version} of {latest}
          {content?.author === "user" && " · Edited by you"}
        </span>
        <button
          className="ib"
          aria-label="Next version"
          disabled={version >= latest}
          onClick={() => {
            onStep(version + 1);
          }}
        >
          <Icon name="chevr" />
        </button>
      </div>
      {loaded === undefined && <p className="note">Loading...</p>}
      {content === null && (
        <div className="note">
          This version could not be loaded.{" "}
          <button className="lnk" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}
      {content != null && (
        // Another version is another page: its own bridge, and no question left open.
        <PageFrame
          key={`${content.artifact_id}:${String(content.version)}`}
          frame={frame}
          content={content}
          editable={content.kind === "document" && content.version === latest}
          onSaved={onStep}
          onStored={setSize}
          onChangedElsewhere={reread}
          onAsk={asks.local}
        />
      )}
      {clearing && (
        <Confirm
          title="Clear page data?"
          about="What this artifact's pages saved goes, on every device. This cannot be undone."
          action="Clear"
          onConfirm={() => {
            actions.clearArtifactStorage(artifact.id).then(
              () => {
                setSize(0);
              },
              () => {
                actions.toast("Could not clear the page data", "error");
              },
            );
          }}
          onClose={() => {
            setClearing(false);
          }}
        />
      )}
    </div>
  );
}

/**
 * The size of what the artifact's pages stored (B88), read when it opens and again after a
 * change made elsewhere; a write of the page shown sets it from the reply.
 */
function useStoredSize(id: string) {
  const { actions } = useStore();
  const [stored, setStored] = useState<{ id: string; size: number } | null>(null);
  const [reads, setReads] = useState(0);
  useEffect(() => {
    let current = true;
    void actions.artifactStorage(id).then((found) => {
      if (current && found !== null) setStored({ id, size: found.size });
    });
    return () => {
      current = false;
    };
  }, [actions, id, reads]);
  const setSize = useCallback(
    (size: number) => {
      setStored({ id, size });
    },
    [id],
  );
  const reread = useCallback(() => {
    setReads((n) => n + 1);
  }, []);
  return { size: stored?.id === id ? stored.size : 0, setSize, reread };
}

/**
 * A version's page, which is untrusted agent output (B79, B82): the daemon's whole document
 * for every kind. Scripts run in a frame of its own opaque origin (no allow-same-origin),
 * so they cannot reach the app, its cookie or storage; the injected policy limits what they
 * load. The page reaches the app only through the bridge (B88), whose requests are checked.
 * A page that prints itself (slides, document) may also open the print dialog.
 *
 * The frame's color-scheme is Nest's theme, so the page's prefers-color-scheme follows the
 * app rather than only the phone. A theme change makes a new frame: WebKit may not
 * re-evaluate prefers-color-scheme in a document already open.
 */
function PageFrame(props: FrameProps) {
  const scheme = useScheme();
  return <BridgedFrame key={scheme} {...props} scheme={scheme} />;
}

interface FrameProps {
  frame: RefObject<HTMLIFrameElement | null>;
  content: ArtifactContent;
  // The latest version of a document: its page may save the user's edit.
  editable: boolean;
  // Shows the version a save made.
  onSaved: (version: number) => void;
  // The stored size after the page's own write.
  onStored: (size: number) => void;
  onChangedElsewhere: () => void;
  // Runs the page's question, showing that it does.
  onAsk: (run: () => Promise<ArtifactAnswer>) => Promise<ArtifactAnswer>;
}

/** A question a page's request puts to the user; the answer is the request's reply. */
interface Question {
  title: string;
  about: string;
  action: string;
  // Runs in the click on the action, so it may download or open a window.
  yes: () => unknown;
  // Why the request was declined on Cancel.
  no: string;
}

interface Asking extends Question {
  answer: (result: unknown) => void;
  decline: (error: BridgeError) => void;
}

// Asks a day when a reply or event lacks the limit: the default of [artifacts] ask_daily_limit.
const ASK_LIMIT = 20;

/** The page's error for a refused ask. */
function askRefusal(error: unknown): BridgeError {
  if (!(error instanceof ApiError)) {
    return new BridgeError("unavailable", "Claude could not answer.");
  }
  if (error.status === 429) {
    const resets = error.data.resets_at;
    const when = resetLabel(typeof resets === "string" ? resets : null, new Date());
    return new BridgeError("budget", `Today's asks for this page are used up. ${when}.`);
  }
  if (error.status === 403) return new BridgeError("disabled", error.message);
  if (error.status === 409) return new BridgeError("busy", error.message);
  return new BridgeError("unavailable", error.message);
}

/**
 * Whether Claude is answering one of the artifact's pages, here or on another device (the
 * Mac's `artifact.ask` events), and today's count: read on opening when the pages have
 * asked today, then from each answer and finished ask.
 */
function useAsks(id: string) {
  const { actions } = useStore();
  const [running, setRunning] = useState(0);
  const [elsewhere, setElsewhere] = useState(false);
  const [count, setCount] = useState<{ remaining: number; limit: number } | null>(null);
  const counted = useCallback((remaining: unknown, limit: unknown) => {
    if (typeof remaining !== "number") return;
    setCount({ remaining, limit: typeof limit === "number" ? limit : ASK_LIMIT });
  }, []);
  // Today's count on opening, once the artifact's pages have asked.
  useEffect(() => {
    let current = true;
    void actions.askStatus(id).then((status) => {
      if (current && status !== null && status.used > 0) counted(status.remaining, status.limit);
    });
    return () => {
      current = false;
    };
  }, [actions, id, counted]);
  useEffect(
    () =>
      actions.onEvent((event) => {
        const p = event.payload;
        if (event.type !== "artifact.ask" || p.artifact_id !== id) return;
        setElsewhere(p.state === "started");
        if (p.state === "finished") counted(p.remaining, p.limit);
      }),
    [actions, id, counted],
  );
  const local = useCallback(
    async (run: () => Promise<ArtifactAnswer>) => {
      setRunning((n) => n + 1);
      try {
        const answer = await run();
        counted(answer.remaining, answer.limit);
        return answer;
      } finally {
        setRunning((n) => n - 1);
      }
    },
    [counted],
  );
  return { asking: running > 0 || elsewhere, count, local };
}

// The page's own storage changes not yet echoed back by the daemon, kept to this many.
const OWN_CHANGES = 50;

/** The same text for the same change, whatever order its keys came in. */
function changeKey({ set, remove, clear }: Omit<ArtifactStorageChange, "artifact_id">): string {
  const entries = Object.entries(set).sort(([a], [b]) => (a < b ? -1 : 1));
  return JSON.stringify([clear, entries, [...remove].sort()]);
}

/** The bytes of a file a page offers. */
function fileBlob({ content, encoding }: FileToSave): Blob {
  const bytes =
    encoding === "base64"
      ? Uint8Array.from(atob(content), (char) => char.charCodeAt(0))
      : new TextEncoder().encode(content);
  return new Blob([bytes], { type: "application/octet-stream" });
}

/** One frame and its bridge; a question it asked goes when the frame does. */
function BridgedFrame({
  frame,
  content,
  editable,
  onSaved,
  onStored,
  onChangedElsewhere,
  onAsk,
  scheme,
}: FrameProps & { scheme: string }) {
  const { actions } = useStore();
  const [asking, setAsking] = useState<Asking | null>(null);
  // Set at once, so a second request in the same tick is refused too.
  const busy = useRef(false);
  const saving = useRef(false);
  const own = useRef<string[]>([]);
  // The page read usage, so usage changes reach it.
  const readsUsage = useRef(false);
  const id = content.artifact_id;

  // Changes made elsewhere reach the page as host events; its own come back as echoes.
  useEffect(
    () =>
      actions.onArtifactStorage((change) => {
        if (change.artifact_id !== id) return;
        const at = own.current.indexOf(changeKey(change));
        if (at >= 0) {
          own.current.splice(at, 1);
          return;
        }
        const page = frame.current?.contentWindow;
        for (const event of storageEvents(change)) page?.postMessage(event, "*");
        onChangedElsewhere();
      }),
    [actions, id, frame, onChangedElsewhere],
  );

  useEffect(
    () =>
      actions.onEvent((event) => {
        if (event.type !== "usage.updated" || !readsUsage.current) return;
        actions.pageUsage(true).then(
          (usage) => {
            frame.current?.contentWindow?.postMessage({ nest: 1, event: "usage", usage }, "*");
          },
          () => undefined,
        );
      }),
    [actions, frame],
  );

  const ask = (question: Question) => {
    if (busy.current) throw new BridgeError("busy", "Nest is already asking the user something.");
    busy.current = true;
    return new Promise((answer, decline) => {
      setAsking({ ...question, answer, decline });
    });
  };

  /** Runs the page's storage change, expecting its echo, which a refusal will not have. */
  const store = async (key: string, change: () => Promise<{ size: number }>) => {
    own.current = [...own.current, key].slice(-OWN_CHANGES);
    try {
      const { size } = await change();
      onStored(size);
      return { size };
    } catch (error) {
      own.current.splice(own.current.indexOf(key), 1);
      throw error;
    }
  };

  const handlers: Handlers = {
    openLink: ({ url }) =>
      ask({
        title: "Open link?",
        about: linkMessage(url),
        action: "Open",
        yes: () => {
          window.open(url, "_blank", "noopener,noreferrer");
          return { opened: true };
        },
        no: "The user did not open the link.",
      }),
    saveFile: (file) => {
      const blob = fileBlob(file);
      return ask({
        title: `Save “${file.name}”?`,
        about: `${sizeText(blob.size)}, offered by this page.`,
        action: "Save",
        yes: () => {
          download(file.name, blob);
          return { saved: true };
        },
        no: "The user did not save the file.",
      });
    },
    storageWrite: async (write) => {
      try {
        return await store(changeKey({ ...write, clear: false }), () =>
          actions.writeArtifactStorage(id, write),
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 413) {
          throw new BridgeError("quota", error.message);
        }
        if (error instanceof ApiError && error.status === 422) {
          throw new BridgeError("bad_request", error.message);
        }
        throw new BridgeError("unavailable", "Nest could not store that.");
      }
    },
    storageClear: async () => {
      try {
        return await store(changeKey({ set: {}, remove: [], clear: true }), async () => {
          await actions.clearArtifactStorage(id);
          return { size: 0 };
        });
      } catch {
        throw new BridgeError("unavailable", "Nest could not clear the page data.");
      }
    },
    usage: async () => {
      readsUsage.current = true;
      try {
        return await actions.pageUsage();
      } catch {
        throw new BridgeError("unavailable", "Nest could not read your usage.");
      }
    },
    ask: async (question) => {
      try {
        const { text, remaining } = await onAsk(() => actions.askArtifact(id, question));
        return { text, remaining };
      } catch (error) {
        throw askRefusal(error);
      }
    },
    saveDocument: async ({ content: text, base_version }) => {
      if (!editable) {
        throw new BridgeError("bad_request", "Only the latest version of a document is saved.");
      }
      if (saving.current) throw new BridgeError("busy", "Nest is already saving this document.");
      saving.current = true;
      try {
        const saved = await actions.saveArtifactDocument(id, text, base_version);
        // After the reply goes out: showing the new version replaces this page.
        setTimeout(() => {
          onSaved(saved.version);
        }, 0);
        return { version: saved.version };
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          throw new BridgeError("conflict", "This document changed since this version.");
        }
        throw new BridgeError(
          "unavailable",
          error instanceof ApiError ? error.message : "Nest could not save the document.",
        );
      } finally {
        saving.current = false;
      }
    },
  };
  useArtifactBridge(frame, handlers);
  return (
    <>
      <iframe
        ref={frame}
        className="affr"
        title={content.title}
        sandbox={PRINTABLE.has(content.kind) ? "allow-scripts allow-modals" : "allow-scripts"}
        referrerPolicy="no-referrer"
        style={{ colorScheme: scheme }}
        srcDoc={withCsp(content.page)}
      />
      {asking !== null && (
        <Confirm
          neutral
          title={asking.title}
          about={asking.about}
          action={asking.action}
          onConfirm={() => {
            asking.answer(asking.yes());
          }}
          onClose={() => {
            busy.current = false;
            setAsking(null);
            // The action closes the sheet before it confirms; a promise keeps its first
            // answer, so declining a moment later changes nothing after it.
            queueMicrotask(() => {
              asking.decline(new BridgeError("declined", asking.no));
            });
          }}
        />
      )}
    </>
  );
}
