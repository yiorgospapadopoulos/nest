// A pending approval with its actions, as the Mac's ApprovalCard: a permission prompt,
// the agent's questions, a plan, a merge, or work to review, on a soft fill. In the
// transcript (`inline`) a quiet coloured label names it; the Needs you panel (`panel`)
// shows it under its own row.
import { useEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { computerAskOf, mergeOf, questionsOf, type QuestionView } from "../../api/payloads.ts";
import type { Approval, PlanMode, SessionDiff } from "../../api/types.ts";
import {
  usePermission,
  usePlan,
  useReview,
  useMerge,
  useRestack,
} from "../../screens/approvals/hooks.ts";
import { useStore } from "../../store/context.ts";
import { engineName } from "../../store/selectors.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Markdown } from "../../ui/Markdown.tsx";
import { Button, Segmented, Toggle } from "../ui/controls.tsx";
import { DiffBar, DiffCounts } from "./bits.tsx";
import { ComputerAskBody } from "./Computer.tsx";
import { Glyph } from "./glyphs.tsx";
import { PublishSheet } from "./PublishSheet.tsx";
import { useQuestionPicks } from "./questionPicks.ts";
import { DiffSheet } from "./ReviewSheets.tsx";

export type CardStyle = "inline" | "panel";

const TITLES: Record<Approval["kind"], string> = {
  permission: "Permission needed",
  question: "Question",
  plan: "Plan ready for review",
  merge: "Ready to merge",
  review: "Ready for review",
  review_comments: "Review comments",
  restack: "Branch to move",
};

const COMPUTER_TITLE = "Needs approval";

export function ApprovalCard({ approval, style }: { approval: Approval; style: CardStyle }) {
  const { state } = useStore();
  const session = state.sessions[approval.session_id];
  const green = approval.kind === "review" || approval.kind === "merge";
  const computer = computerAskOf(approval);
  const title =
    approval.kind === "question"
      ? `Question from ${engineName(state, session?.provider)}`
      : computer !== null
        ? COMPUTER_TITLE
        : TITLES[approval.kind];
  let body: ReactNode;
  switch (approval.kind) {
    case "permission":
      body =
        computer === null ? (
          <PermissionBody approval={approval} />
        ) : (
          <ComputerAskBody approval={approval} ask={computer} />
        );
      break;
    case "question":
      body = <QuestionBody approval={approval} />;
      break;
    case "plan":
      body = <PlanBody approval={approval} style={style} />;
      break;
    case "merge":
      body = <MergeBody approval={approval} />;
      break;
    case "review":
      body = <ReviewBody approval={approval} style={style} />;
      break;
    case "review_comments":
      body = <p className="dc-ask-t">{approval.title}</p>;
      break;
    case "restack":
      body = <RestackBody approval={approval} />;
      break;
  }
  return (
    <div className={`dc-ask ${style}`} role="group" aria-label={title}>
      {style === "inline" && (
        <span className={green ? "dc-ask-l ok" : "dc-ask-l"}>
          <span className="dc-dot" />
          {title}
        </span>
      )}
      {body}
    </div>
  );
}

/** The card's buttons; a narrow pane wraps them instead of spilling out. */
function ActionRow({ children, ref }: { children: ReactNode; ref?: Ref<HTMLDivElement> }) {
  return (
    <div ref={ref} className="dc-ask-acts">
      {children}
    </div>
  );
}

/** The command in mono, why it asks, and Approve, Reject, Always allow. */
function PermissionBody({ approval }: { approval: Approval }) {
  const { state } = useStore();
  const { view, busy, decide } = usePermission(approval, state.sessions[approval.session_id]);
  return (
    <>
      <div className="dc-cmdbox">
        {view.tool === "Bash" ? `Bash ${view.command}` : view.command}
      </div>
      {view.why !== null && <p className="dc-ask-t">{view.why}</p>}
      {view.reason !== null && <p className="dc-ask-why lines">{view.reason}</p>}
      <ActionRow>
        <Button kind="primary" disabled={busy} onClick={() => void decide("allow")}>
          Approve
        </Button>
        <Button disabled={busy} onClick={() => void decide("deny")}>
          Reject
        </Button>
        {view.canAlways && (
          <Button
            kind="plain"
            disabled={busy}
            title={`Allow ${view.always} without asking again`}
            className="dc-always"
            onClick={() => void decide("allow", true)}
          >
            {`Always allow ${view.always}`}
          </Button>
        )}
        {busy && <Fireflies size={9} />}
      </ActionRow>
    </>
  );
}

type Answer = string | string[];

function recommended(q: QuestionView): string[] {
  const labels = q.options.filter((o) => o.recommended).map((o) => o.label);
  return q.multiSelect ? labels : labels.slice(0, 1);
}

/** The answer to send; Other chosen with no text is no answer yet. */
function answerOf(q: QuestionView, picked: string[], other: string | null): Answer {
  if (other === null) return q.multiSelect ? picked : picked.join("");
  const typed = other.trim();
  if (!q.multiSelect) return typed;
  return typed === "" ? [] : [...picked, typed];
}

/** Each question with its options (the recommended one chosen to start), Other, Send answer. */
function QuestionBody({ approval }: { approval: Approval }) {
  const { state, actions } = useStore();
  const questions = questionsOf(approval);
  // Shared with this approval's other card, in the chat or in Needs you.
  const { picked, others, setPicked, setOthers } = useQuestionPicks(approval.id);
  const chosenOf = (q: QuestionView) => picked[q.question] ?? recommended(q);
  const [busy, setBusy] = useState(false);
  // Choosing Other here focuses its field and brings Send answer into view; the other
  // card of the approval shows the field without taking the keyboard.
  const fields = useRef(new Map<string, HTMLInputElement>());
  const acts = useRef<HTMLDivElement>(null);
  const [revealed, setRevealed] = useState<{ question: string } | null>(null);
  useEffect(() => {
    if (revealed === null) return;
    fields.current.get(revealed.question)?.focus();
    acts.current?.scrollIntoView({ block: "nearest" });
  }, [revealed]);
  const answers = Object.fromEntries(
    questions.map((q) => [q.question, answerOf(q, chosenOf(q), others[q.question] ?? null)]),
  );
  const complete = Object.values(answers).every((a) => a.length > 0);
  const agent = engineName(state, state.sessions[approval.session_id]?.provider);
  const run = async (resolve: () => Promise<boolean>) => {
    setBusy(true);
    if (!(await resolve())) setBusy(false);
  };
  return (
    <>
      {questions.map((q) => {
        const chosen = chosenOf(q);
        const other = others[q.question] ?? null;
        const choose = (label: string) => {
          setPicked({
            ...picked,
            [q.question]: q.multiSelect
              ? chosen.includes(label)
                ? chosen.filter((l) => l !== label)
                : [...chosen, label]
              : [label],
          });
          if (!q.multiSelect) setOthers({ ...others, [q.question]: null });
        };
        const toggleOther = () => {
          if (!q.multiSelect) setPicked({ ...picked, [q.question]: [] });
          setOthers({ ...others, [q.question]: other === null ? "" : q.multiSelect ? null : "" });
          if (other === null) setRevealed({ question: q.question });
        };
        return (
          <fieldset key={q.question} className="dc-q">
            <legend className="dc-qt">{q.question}</legend>
            <div
              role={q.multiSelect ? "group" : "radiogroup"}
              aria-label={q.question}
              className="dc-qopts"
            >
              {q.options.map((o) => (
                <Option
                  key={o.label}
                  on={chosen.includes(o.label)}
                  multi={q.multiSelect}
                  label={o.label}
                  recommended={o.recommended}
                  description={o.description}
                  onClick={() => {
                    choose(o.label);
                  }}
                />
              ))}
              <Option
                on={other !== null}
                multi={q.multiSelect}
                label="Other"
                recommended={false}
                description={null}
                onClick={toggleOther}
              />
            </div>
            {other !== null && (
              <input
                className="dc-cfield"
                aria-label="Type your answer"
                placeholder="Type your answer"
                autoComplete="off"
                ref={(input) => {
                  if (input === null) fields.current.delete(q.question);
                  else fields.current.set(q.question, input);
                }}
                value={other}
                onChange={(event) => {
                  setOthers({ ...others, [q.question]: event.target.value });
                }}
              />
            )}
          </fieldset>
        );
      })}
      <ActionRow ref={acts}>
        <Button
          kind="primary"
          disabled={!complete || busy}
          onClick={() => void run(() => actions.resolve(approval, { answers }, "Answer sent"))}
        >
          Send answer
        </Button>
        <Button
          kind="plain"
          disabled={busy}
          title={`Let ${agent} continue without an answer`}
          onClick={() =>
            void run(() => actions.resolve(approval, { dismiss: true }, "Question dismissed"))
          }
        >
          Dismiss
        </Button>
      </ActionRow>
    </>
  );
}

function Option({
  on,
  multi,
  label,
  recommended: rec,
  description,
  onClick,
}: {
  on: boolean;
  multi: boolean;
  label: string;
  recommended: boolean;
  description: string | null;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={on ? "dc-opt on" : "dc-opt"}
      role={multi ? "checkbox" : "radio"}
      aria-checked={on}
      onClick={onClick}
    >
      <span className={multi ? "dc-mark multi" : "dc-mark"} aria-hidden="true" />
      <span className="dc-optb">
        <span className="dc-optl">
          {label}
          {rec && <span className="dc-rec">Recommended</span>}
        </span>
        {description !== null && <span className="dc-optd">{description}</span>}
      </span>
    </button>
  );
}

/** The plan rendered, how the chat goes on after it, an optional note, and the two answers. */
function PlanBody({ approval, style }: { approval: Approval; style: CardStyle }) {
  const { state } = useStore();
  const { busy, plan, modes, approve, keepPlanning } = usePlan(approval);
  const [mode, setMode] = useState<PlanMode>("acceptEdits");
  const [note, setNote] = useState("");
  const agent = engineName(state, state.sessions[approval.session_id]?.provider);
  return (
    <>
      <div className={style === "panel" ? "dc-plan scroll" : "dc-plan"}>
        <Markdown text={plan} />
      </div>
      <div className="dc-ask-seg" title={`How ${agent} goes on once you approve the plan`}>
        <Segmented
          label="Then"
          value={mode}
          options={modes.map((m) => ({ value: m.value, label: m.label }))}
          onChange={setMode}
        />
      </div>
      <input
        className="dc-cfield"
        aria-label={`Note for ${agent} (optional)`}
        placeholder={`Note for ${agent} (optional)`}
        autoComplete="off"
        value={note}
        onChange={(event) => {
          setNote(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") void keepPlanning(note);
        }}
      />
      <ActionRow>
        <Button
          kind="primary"
          disabled={busy}
          title="Continue with this plan in the mode chosen above"
          onClick={() => void approve(mode)}
        >
          Approve plan
        </Button>
        <Button
          disabled={busy}
          title={`Send ${agent} back to planning, with the note if you wrote one`}
          onClick={() => void keepPlanning(note)}
        >
          Keep planning
        </Button>
      </ActionRow>
    </>
  );
}

/** Merge (squash), with the choice to delete the chat's branch too, off by default (B96). */
function MergeBody({ approval }: { approval: Approval }) {
  const { actions } = useStore();
  const { view, busy, merge } = useMerge(approval);
  const [deleteBranch, setDeleteBranch] = useState(false);
  const pr = mergeOf(approval);
  return (
    <>
      <p className="dc-ask-t">
        <span className="dc-mono">#{pr.number}</span> {pr.title}
      </p>
      <label className="dc-ask-ck">
        <Toggle checked={deleteBranch} onChange={setDeleteBranch} label="Also delete the branch" />
        Also delete the branch
      </label>
      <ActionRow>
        <Button kind="primary" disabled={busy} onClick={() => void merge(deleteBranch)}>
          Merge (squash)
        </Button>
        {view.url !== "" && (
          <a className="dk-btn k-plain" href={view.url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        )}
        <Button
          kind="plain"
          disabled={busy}
          onClick={() => void actions.resolve(approval, { dismiss: true }, "Merge dismissed")}
        >
          Dismiss
        </Button>
      </ActionRow>
    </>
  );
}

/** A stacked branch to move onto where the branch under it went, then Dismiss (B149). */
function RestackBody({ approval }: { approval: Approval }) {
  const { actions } = useStore();
  const { view, title, action, busy, restack } = useRestack(approval);
  return (
    <>
      <p className="dc-ask-t">{title}</p>
      {view.error !== null && <p className="dc-ask-why lines">{view.error}</p>}
      <ActionRow>
        <Button kind="primary" disabled={busy} onClick={() => void restack()}>
          {action.label}
        </Button>
        {view.url !== null && (
          <a className="dk-btn k-plain" href={view.url} target="_blank" rel="noreferrer">
            Open on GitHub
          </a>
        )}
        <Button
          kind="plain"
          disabled={busy}
          onClick={() => void actions.resolve(approval, { dismiss: true }, "Dismissed")}
        >
          Dismiss
        </Button>
      </ActionRow>
    </>
  );
}

/** The work's stats and View changes; Approve opens the commit message (B56). */
function ReviewBody({ approval, style }: { approval: Approval; style: CardStyle }) {
  const { state } = useStore();
  const session = state.sessions[approval.session_id];
  const review = useReview(approval, session);
  const [sheet, setSheet] = useState<"diff" | "publish" | "commit" | null>(null);
  const [feedback, setFeedback] = useState("");
  const git = state.repos.find((r) => r.name === approval.repo)?.git !== false;
  const agent = engineName(state, session?.provider);
  const close = () => {
    setSheet(null);
  };
  const send = () => {
    if (feedback.trim() === "") return;
    void review.feedback(feedback.trim());
    setFeedback("");
  };
  return (
    <>
      {style === "panel" && <p className="dc-ask-t strong">{approval.title}</p>}
      <div className="dc-ask-stat">
        <DiffCounts
          added={review.view.additions}
          removed={review.view.deletions}
          files={review.view.files}
        />
        <DiffBar added={review.view.additions} removed={review.view.deletions} />
        <span className="grow" />
        {git && (
          <button
            className="dc-linkbtn"
            onClick={() => {
              setSheet("diff");
            }}
          >
            View changes
          </button>
        )}
      </div>
      {style === "panel" && review.view.summary !== null && (
        <p className="dc-ask-t">{review.view.summary}</p>
      )}
      {style === "panel" && <FileList paths={review.view.paths} diff={review.diff} />}
      {style === "panel" && (
        <div className="dc-ask-fb">
          <input
            className="dc-cfield"
            aria-label={`Feedback for ${agent}`}
            placeholder={`Feedback for ${agent}`}
            autoComplete="off"
            value={feedback}
            onChange={(event) => {
              setFeedback(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") send();
            }}
          />
          <Button
            disabled={feedback.trim() === ""}
            title="Send feedback to the chat"
            onClick={send}
          >
            Send
          </Button>
        </div>
      )}
      <ActionRow>
        <Button
          kind="primary"
          disabled={!git}
          title={git ? undefined : "Not a git repository: nothing to commit"}
          onClick={() => {
            setSheet("publish");
          }}
        >
          {review.approveLabel}
        </Button>
        {review.offersCommitOnly && (
          <Button
            kind="plain"
            title="Commit without pushing; the pull request stays as it is"
            onClick={() => {
              setSheet("commit");
            }}
          >
            Approve and commit
          </Button>
        )}
      </ActionRow>
      {review.replyNote !== null && <p className="dc-ask-why">{review.replyNote}</p>}
      {sheet === "diff" && (
        <DiffSheet
          review={review}
          onClose={close}
          onApprove={(commitOnly) => {
            setSheet(commitOnly ? "commit" : "publish");
          }}
        />
      )}
      {(sheet === "publish" || sheet === "commit") && (
        <PublishSheet
          approval={approval}
          session={session}
          review={review}
          commitOnly={sheet === "commit"}
          onClose={close}
        />
      )}
    </>
  );
}

const FILES_SHOWN = 3;

/** The reviewed paths, with their line counts once the diff is loaded. */
function FileList({ paths, diff }: { paths: string[]; diff: SessionDiff | null }) {
  if (paths.length === 0) return null;
  return (
    <ul className="dc-flist" aria-label="Changed files">
      {paths.slice(0, FILES_SHOWN).map((path) => {
        const file = diff?.files.find((f) => f.path === path);
        return (
          <li key={path}>
            <Glyph name="file" size={10} />
            <span className="dc-flistp" title={path}>
              {path}
            </span>
            {file !== undefined && <DiffCounts added={file.additions} removed={file.deletions} />}
          </li>
        );
      })}
      {paths.length > FILES_SHOWN && (
        <li className="dc-flistm">{`and ${String(paths.length - FILES_SHOWN)} more files`}</li>
      )}
    </ul>
  );
}
