import type { Artifact, ArtifactContent } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { Icon } from "../../ui/Icon.tsx";
import { Markdown } from "../../ui/Markdown.tsx";
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

/** One version of an artifact: where it came from, the version stepper and the document. */
export function ArtifactReader({ artifact, version, loaded, onStep, onRetry }: Props) {
  if (artifact === undefined) return <p className="note">Loading...</p>;
  const content = loaded?.content;
  const latest = artifact.latest_version;
  return (
    <div className="afrd">
      <div className="afmeta">
        <span className="afk">
          <Icon name={KIND_ICONS[artifact.kind]} />
          {KIND_LABELS[artifact.kind]}
        </span>
        <span className="afo">{originOf(artifact)}</span>
        {content != null && <span>{activityTime(content.created_at, new Date())}</span>}
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
      {content != null &&
        (content.kind === "html" ? (
          <HtmlFrame title={content.title} html={content.content} />
        ) : (
          <div className="afdoc">
            <Markdown text={content.content} />
          </div>
        ))}
    </div>
  );
}

/**
 * An HTML artifact, which is untrusted agent output (contract section 6): scripts run in a
 * frame of its own opaque origin (no allow-same-origin), so they cannot reach the app, its
 * cookie or storage; the injected policy lets them load nothing. The app never listens to
 * messages from the frame.
 */
export function HtmlFrame({ title, html }: { title: string; html: string }) {
  return (
    <iframe
      className="affr"
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      srcDoc={withCsp(html)}
    />
  );
}
