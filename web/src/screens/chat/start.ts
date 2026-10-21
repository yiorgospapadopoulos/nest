import {
  mergeOf,
  permissionOf,
  planOf,
  questionsOf,
  reviewCommentsDetail,
  reviewOf,
} from "../../api/payloads.ts";
import type { Approval, Session } from "../../api/types.ts";
import { ciFailure, pendingFor, stuckChats, type Tone } from "../../store/selectors.ts";
import type { State } from "../../store/state.ts";

// The new chat screen (B90 design I fitted to the phone, B102), as NestKit's StartScreen.

/** The ways to ask, as the words before and after the project. */
const QUESTIONS: [lead: string, link: string, tail: string][] = [
  ["What should we work on", "in", ""],
  ["What's next", "for", ""],
  ["Where should we start", "in", ""],
  ["What are we building", "in", " today"],
  ["What needs doing", "in", ""],
  ["What should we fix or build", "in", ""],
  ["What's on your mind", "for", ""],
  ["What shall we tackle", "in", ""],
];

export const QUESTION_COUNT = QUESTIONS.length;

/** The question at `index`, wrapping past the end. */
export function question(index: number, project: string): string {
  const [lead, link, tail] = QUESTIONS[index % QUESTION_COUNT] as [string, string, string];
  return `${lead} ${link} ${project}${tail}?`;
}

/** Which question shows: the next one each time the screen appears, never one twice in a row. */
export function rotation(): { next: () => number } {
  let current: number | null = null;
  return {
    next: () => {
      current = current === null ? 0 : (current + 1) % QUESTION_COUNT;
      return current;
    },
  };
}

// For the app's lifetime, as the Mac keeps it per window.
export const questions = rotation();

/** "now", "4m", "2h", "1d": the largest whole unit only. */
export function age(iso: string, now: Date): string {
  const minutes = Math.floor(Math.max(0, now.getTime() - Date.parse(iso)) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${String(minutes)}m`;
  if (minutes < 1440) return `${String(Math.floor(minutes / 60))}h`;
  return `${String(Math.floor(minutes / 1440))}d`;
}

const line = (kind: string, detail: string | null | undefined) =>
  detail == null || detail === "" ? kind : `${kind} · ${detail}`;

/** What an approval needs, in the one line of a Needs you row (B77): its kind and a detail. */
export function needsYouLine(approval: Approval): string {
  switch (approval.kind) {
    case "question":
      return line("Question", questionsOf(approval)[0]?.question);
    case "review": {
      const { files, additions, deletions } = reviewOf(approval);
      const noun = files === 1 ? "file" : "files";
      return line(
        "Ready for review",
        `+${String(additions)} -${String(deletions)} in ${String(files)} ${noun}`,
      );
    }
    case "plan":
      return line("Plan", firstLine(planOf(approval)));
    case "merge": {
      const { number, title } = mergeOf(approval);
      return line("Ready to merge", `#${String(number)} ${title}`);
    }
    case "review_comments":
      return line("Review comments", reviewCommentsDetail(approval));
    default: {
      const { tool, command } = permissionOf(approval, null);
      // A command reads as the others do, after its tool's name.
      return line("Permission", tool === "Bash" ? `Bash ${command}` : command);
    }
  }
}

/** A plan's first line with text, without its Markdown heading marks. */
function firstLine(markdown: string): string | undefined {
  return markdown
    .split("\n")
    .map((l) => l.replace(/^#+/, "").trim())
    .find((l) => l !== "");
}

export interface Waiting {
  id: string;
  chat: string;
  title: string;
  tone: Tone;
  line: string;
}

export interface StartLists {
  waiting: Waiting[];
  recent: Session[];
}

// As many recent chats as the Mac lists beside its composer.
const RECENT = 4;

/** "Waiting on you" (approvals, failed checks, stuck chats) and "Recent" for a project. */
export function startLists(state: State, repo: string): StartLists {
  const sessions = Object.values(state.sessions).filter((s) => s.repo === repo);
  const titleOf = (a: Approval) => state.sessions[a.session_id]?.title ?? a.title;
  const approvals: Waiting[] = Object.values(state.approvals)
    .filter((a) => a.repo === repo)
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((a) => ({
      id: `approval-${a.id}`,
      chat: a.session_id,
      title: titleOf(a),
      tone: a.kind === "review" || a.kind === "merge" ? "rev" : "wait",
      line: needsYouLine(a),
    }));
  const failed = sessions.flatMap((s): Waiting[] => {
    const failure = ciFailure(s, pendingFor(state, s.id));
    if (failure === null) return [];
    return [
      {
        id: `checks-${s.id}`,
        chat: s.id,
        title: s.title,
        tone: "fail",
        line: line("Checks failed", failure.names.join(", ")),
      },
    ];
  });
  const stuck: Waiting[] = stuckChats(state)
    .filter((c) => c.repo === repo)
    .map(({ session, stuck: flag }) => ({
      id: `stuck-${session.id}`,
      chat: session.id,
      title: session.title,
      tone: "wait",
      line: line("Stuck", flag.details),
    }));
  const waiting = [...approvals, ...failed, ...stuck];
  const listed = new Set(waiting.map((w) => w.chat));
  const recent = sessions
    .filter((s) => s.archived_at === null && !listed.has(s.id))
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id))
    .slice(0, RECENT);
  return { waiting, recent };
}
