import { useEffect, useState } from "react";
import type { IssueList, IssueRef, IssueShow, IssueSummary } from "../../api/types.ts";
import { issueLine, ISSUES_EVERY_MS } from "./start.ts";
import { useStore } from "../../store/context.ts";
import { useRowGestures } from "../projects/rowGestures.ts";

// The list shows this many rows, then "N more", as Waiting on you.
const FIRST = 3;
/**
 * The project's open issues, read when the screen appears, every minute while it shows and
 * when the page becomes visible again; null until read, or while GitHub cannot be read.
 */
function useIssues(repo: string) {
  const { actions } = useStore();
  const [list, setList] = useState<IssueList | null>(null);
  const [reads, setReads] = useState(0);
  useEffect(() => {
    let current = true;
    void actions.issues(repo).then((read) => {
      // A failed read keeps the list it had, for the next read to try again.
      if (current && read !== null) setList(read);
    });
    return () => {
      current = false;
    };
  }, [actions, repo, reads]);
  useEffect(() => {
    const again = () => {
      setReads((n) => n + 1);
    };
    const timer = window.setInterval(again, ISSUES_EVERY_MS);
    const visible = () => {
      if (document.visibilityState === "visible") again();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);
  const choose = (show: IssueShow) => {
    actions.chooseIssueShow(repo, show);
    setList((shown) => (shown === null ? null : { ...shown, show }));
    setReads((n) => n + 1);
  };
  return { list, choose };
}

interface Props {
  repo: string;
  // Opens the chat already started from an issue.
  onOpen: (sessionId: string) => void;
  // Puts the issue in the draft, to start a new chat from it.
  onStart: (issue: IssueRef) => void;
}

/**
 * "Open issues · N" with All · Mine on its label (B101): each issue's title over its line.
 * A tap opens the issue's chat when it has one, else puts the issue in the draft; a
 * long-press starts a new chat from it anyway, as the Mac's Option-click. Left out when the
 * project has no GitHub remote or GitHub cannot be read.
 */
export function IssuesSection({ repo, onOpen, onStart }: Props) {
  const { list, choose } = useIssues(repo);
  const [more, setMore] = useState(false);
  if (list?.available !== true) return null;
  const { issues, show } = list;
  // With Mine and none of the user's, the section stays so its switch does.
  if (issues.length === 0 && show === "all") return null;
  const shown = more ? issues : issues.slice(0, FIRST);
  return (
    <section className="nc-l" aria-label="Open issues">
      <h3 className="lbl nc-il">
        <span>Open issues · {issues.length}</span>
        <span className="nc-sw" role="group" aria-label="Which issues">
          {(["all", "mine"] as const).map((value) => (
            <button
              key={value}
              aria-pressed={show === value}
              onClick={() => {
                choose(value);
              }}
            >
              {value === "all" ? "All" : "Mine"}
            </button>
          ))}
        </span>
      </h3>
      {shown.map((issue) => (
        <IssueRow key={issue.number} issue={issue} onOpen={onOpen} onStart={onStart} />
      ))}
      {issues.length > FIRST && !more && (
        <button
          className="nc-more"
          onClick={() => {
            setMore(true);
          }}
        >
          {issues.length - FIRST} more
        </button>
      )}
    </section>
  );
}

function IssueRow({
  issue,
  onOpen,
  onStart,
}: {
  issue: IssueSummary;
  onOpen: (sessionId: string) => void;
  onStart: (issue: IssueRef) => void;
}) {
  const start = () => {
    onStart({ number: issue.number, title: issue.title, url: issue.url });
  };
  const gestures = useRowGestures(() => {
    if (issue.chat === null) start();
    else onOpen(issue.chat);
  }, start);
  return (
    <button
      className="nc-r nc-i"
      aria-label={`${issue.title}, ${issueLine(issue)}${issue.chat === null ? "" : ", has a chat"}`}
      {...gestures}
    >
      <span className="nc-t">{issue.title}</span>
      <span className="nc-m">{issueLine(issue)}</span>
    </button>
  );
}
