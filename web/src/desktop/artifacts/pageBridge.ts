// The host side of an open page's bridge (B88), as the phone reader answers it
// (screens/artifacts/ArtifactReader.tsx, BridgedFrame): the same checks (bridge.ts), the
// same replies and the same questions to the user.
import { useEffect, useRef, useState, type RefObject } from "react";
import { ApiError } from "../../api/client.ts";
import type { ArtifactAnswer, ArtifactContent, ArtifactStorageChange } from "../../api/types.ts";
import { resetLabel, sizeText } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import {
  BridgeError,
  linkMessage,
  storageEvents,
  useArtifactBridge,
  type FileToSave,
  type Handlers,
} from "../../screens/artifacts/bridge.ts";
import { download } from "../../screens/artifacts/files.ts";
import { useBridge } from "../context.ts";
import { openLink } from "../links.ts";

/** A question a page's request puts to the user; the answer is the request's reply. */
export interface Question {
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

export interface PageBridge {
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

/**
 * Answers the page in `frame` for as long as the caller is mounted (one frame: a new
 * version or theme needs a new mount). Returns the question the page asked the user, with
 * its answers; the question goes when the frame does.
 */
export function usePageBridge({
  frame,
  content,
  editable,
  onSaved,
  onStored,
  onChangedElsewhere,
  onAsk,
}: PageBridge) {
  const { actions } = useStore();
  const bridge = useBridge();
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
          openLink(url, bridge);
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
          if (!bridge.native) {
            download(file.name, blob);
            return { saved: true };
          }
          // In the system's save dialog, as the Mac's; cancelling it is not saving.
          const contents =
            file.encoding === "base64" ? { base64: file.content } : { text: file.content };
          return bridge.saveFile(file.name, contents).then((path) => ({ saved: path !== null }));
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

  return {
    question: asking as Question | null,
    confirm: () => {
      asking?.answer(asking.yes());
    },
    // Closing declines; a promise keeps its first answer, so after a confirm it changes nothing.
    close: () => {
      if (asking === null) return;
      busy.current = false;
      setAsking(null);
      queueMicrotask(() => {
        asking.decline(new BridgeError("declined", asking.no));
      });
    },
  };
}
