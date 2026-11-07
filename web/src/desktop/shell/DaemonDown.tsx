import { INSTALL_LINE } from "../layout/connection.ts";
import "../setup/setup.css";
import { useCopy } from "../setup/useCopy.ts";
import { Button } from "../ui/controls.tsx";

/**
 * The window while the daemon cannot be reached at launch (B130, screens Z): the line that
 * repairs the install, or what stops the daemon when the app can tell.
 */
export function DaemonDown({
  problem,
  starting,
  onTryAgain,
}: {
  // What stops it, such as the Secret Service's message; null when unknown.
  problem: string | null;
  starting: boolean;
  onTryAgain: () => void;
}) {
  const { copied, copy } = useCopy(INSTALL_LINE);
  const title = problem === null ? "Nest's background service isn't running" : "Nest can't start";
  return (
    <main className="su-down" aria-label={title}>
      <section>
        <h1>{title}</h1>
        {problem !== null ? (
          <p>{problem}</p>
        ) : (
          <>
            <p>Paste this in Terminal. Your chats stay.</p>
            <code>{INSTALL_LINE}</code>
          </>
        )}
        <div className="su-again">
          {problem === null && (
            <Button kind="primary" size="large" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </Button>
          )}
          <Button
            kind={problem === null ? "soft" : "primary"}
            size="large"
            disabled={starting}
            onClick={onTryAgain}
          >
            Try again
          </Button>
        </div>
      </section>
    </main>
  );
}
