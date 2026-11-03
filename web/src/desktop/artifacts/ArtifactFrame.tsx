import { useScheme } from "../../appearance/scheme.ts";
import { withCsp } from "../../screens/artifacts/html.ts";
import { ConfirmDialog } from "./ConfirmDialog.tsx";
import { usePageBridge, type PageBridge } from "./pageBridge.ts";
import { useStagedPage } from "./staging.ts";
import { exportsPdf } from "./text.ts";

/**
 * A version's page, which is untrusted agent output (B79, B82), as the phone reader frames
 * it: the daemon's whole document for every kind, with the artifact policy put first.
 * Scripts run in a frame of its own opaque origin (no allow-same-origin), so they cannot
 * reach the app or its storage; the policy limits what they load. The page reaches the app
 * only through the bridge (B88), whose requests are checked. A page that prints itself
 * (slides, document) may also open the print dialog.
 *
 * The frame's color-scheme is Nest's theme, so the page's prefers-color-scheme follows the
 * app. A theme change makes a new frame: WebKit may not re-evaluate prefers-color-scheme in
 * a document already open.
 */
export function ArtifactFrame(props: PageBridge) {
  const scheme = useScheme();
  return <BridgedFrame key={scheme} {...props} scheme={scheme} />;
}

/** One frame and its bridge; a question it asked goes when the frame does. */
function BridgedFrame({ scheme, ...props }: PageBridge & { scheme: string }) {
  const { frame, content } = props;
  const { question, confirm, close } = usePageBridge(props);
  const page = withCsp(content.page);
  const source = useStagedPage(page);
  return (
    <>
      <iframe
        ref={frame}
        className="da-frame"
        title={content.title}
        sandbox={exportsPdf(content.kind) ? "allow-scripts allow-modals" : "allow-scripts"}
        referrerPolicy="no-referrer"
        style={{ colorScheme: scheme }}
        {...source}
      />
      {question !== null && (
        <ConfirmDialog
          title={question.title}
          message={question.about}
          action={question.action}
          onConfirm={confirm}
          onClose={close}
        />
      )}
    </>
  );
}
