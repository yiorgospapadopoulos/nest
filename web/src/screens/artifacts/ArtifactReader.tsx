import type { Artifact, ArtifactContent } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { useScheme } from "../../appearance/scheme.ts";
import { Icon } from "../../ui/Icon.tsx";
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
      {content != null && <PageFrame title={content.title} page={content.page} />}
    </div>
  );
}

/**
 * A version's page, which is untrusted agent output (B79, B82): the daemon's whole document
 * for either kind. Scripts run in a frame of its own opaque origin (no allow-same-origin),
 * so they cannot reach the app, its cookie or storage; the injected policy limits what they
 * load. The app never listens to messages from the frame.
 *
 * The frame's color-scheme is Nest's theme, so the page's prefers-color-scheme follows the
 * app rather than only the phone. A theme change makes a new frame: WebKit may not
 * re-evaluate prefers-color-scheme in a document already open.
 */
function PageFrame({ title, page }: { title: string; page: string }) {
  const scheme = useScheme();
  return (
    <iframe
      key={scheme}
      className="affr"
      title={title}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      style={{ colorScheme: scheme }}
      srcDoc={withCsp(page)}
    />
  );
}
