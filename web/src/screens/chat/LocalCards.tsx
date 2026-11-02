import type { LocalApp, LocalModel } from "../../api/types.ts";
import {
  downBody,
  downTitle,
  LOCAL_TITLE,
  NO_IMAGES,
  NO_WEB_SEARCH,
  notLoadedTitle,
  startLabel,
  weakBarText,
  type LocalFailure,
} from "../../store/local.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";

// A chat on a local model (B106, B116 item 8), as the Mac's LocalChatViews.

/** "Local" in a thin outline, after a local chat's title. */
export function LocalTag({ name }: { name: string }) {
  return (
    <span className="ltag" title={`Runs on ${name}, on the Mac`}>
      {LOCAL_TITLE}
    </span>
  );
}

interface FailureProps {
  failure: LocalFailure;
  // Whether the composer holds a message to send again.
  canRetry: boolean;
  starting: boolean;
  onRetry: () => void;
  onStart: (app: LocalApp) => void;
  onChangeModel: () => void;
}

/**
 * Above the composer when the chat's local server did not answer (the message stays in the
 * composer for Retry) or LM Studio could not load the model.
 */
export function LocalFailureCard({
  failure,
  canRetry,
  starting,
  onRetry,
  onStart,
  onChangeModel,
}: FailureProps) {
  const down = failure.code === "local_server_down" ? failure : null;
  const [title, body] =
    failure.code === "local_server_down"
      ? [downTitle(failure), downBody(failure)]
      : [notLoadedTitle(failure), failure.detail];
  return (
    <div className="lcard" role="group" aria-label={title}>
      <b>{title}</b>
      <p>{body}</p>
      <div className="lcard-b">
        <button className="b b-pri" disabled={!canRetry} onClick={onRetry}>
          Retry
        </button>
        {down?.start != null && (
          <button
            className="b"
            disabled={starting}
            onClick={() => {
              if (down.start !== null) onStart(down.start);
            }}
          >
            {startLabel(down.start)}
          </button>
        )}
        <button className="b" onClick={onChangeModel}>
          Change model
        </button>
      </div>
    </div>
  );
}

interface WeakProps {
  model: LocalModel;
  onChangeModel: () => void;
  onDismiss: () => void;
}

/** Above a local chat's composer while its model is weak at tools, until dismissed here. */
export function WeakToolsBar({ model, onChangeModel, onDismiss }: WeakProps) {
  return (
    <div className="lweak" role="group" aria-label="Weak at tools">
      <span className="lweak-i" aria-hidden="true">
        &#9650;
      </span>
      <p>{weakBarText(model)}</p>
      <div className="lweak-b">
        <button className="lnk2" onClick={onChangeModel}>
          Change model
        </button>
        <button className="lnk2 q" onClick={onDismiss}>
          Don&apos;t show again
        </button>
      </div>
    </div>
  );
}

interface AttachProps {
  model: LocalModel;
  onAttach: () => void;
  onClose: () => void;
}

/** A local chat's +: files, and what the model cannot take, greyed with the reason. */
export function LocalAttachSheet({ model, onAttach, onClose }: AttachProps) {
  return (
    <ActionSheet label="Attach" onClose={onClose}>
      <button
        className="asi"
        role="menuitem"
        onClick={() => {
          onClose();
          onAttach();
        }}
      >
        Attach files
      </button>
      {!model.vision && (
        <button className="asi" role="menuitem" disabled>
          <span>
            <span>Attach image</span>
            <small>{NO_IMAGES}</small>
          </span>
        </button>
      )}
      <button className="asi" role="menuitem" disabled>
        <span>
          <span>Web search</span>
          <small>{NO_WEB_SEARCH}</small>
        </span>
      </button>
    </ActionSheet>
  );
}
