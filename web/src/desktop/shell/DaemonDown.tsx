import { Fireflies } from "../../ui/Fireflies.tsx";
import "../setup/setup.css";
import { useCopy } from "../setup/useCopy.ts";
import { Button } from "../ui/controls.tsx";

/**
 * The window while the daemon cannot be reached at launch (B130, screens Z), once starting
 * it by itself did not help: the line that repairs the install, or what stops the daemon
 * when the app can tell.
 */
export function DaemonDown({
  problem,
  line,
  starting,
  onTryAgain,
}: {
  // What stops it, such as the Secret Service's message; null when unknown.
  problem: string | null;
  // The install line, from the address the install came from.
  line: string;
  starting: boolean;
  onTryAgain: () => void;
}) {
  const { copied, copy } = useCopy(line);
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
            <code>{line}</code>
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

/**
 * While the daemon is down for an update: never the repair line, as Nest sees to it. One
 * screen the whole time (B130, fix 30b): the slow line's place is kept from the start, so
 * nothing moves when it appears.
 */
export function UpdatingNest({ version, slow }: { version: string; slow: boolean }) {
  const title = `Updating Nest to ${version}...`;
  return (
    <main className="su-down" aria-label={title}>
      <section>
        <h1>{title}</h1>
        <Fireflies />
        <p className="su-slow" style={{ visibility: slow ? "visible" : "hidden" }}>
          Taking longer than usual
        </p>
      </section>
    </main>
  );
}
