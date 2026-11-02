import { commentPlace, list, num, obj, reviewCommentsOf, str } from "../api/payloads.ts";
import type { Approval, JsonObject } from "../api/types.ts";

/** The part of a user message Nest wrote from GitHub (B101), as NestKit's GitHubMessage. */
export type GitHubPart =
  | {
      kind: "issue";
      // "Issue #47 from GitHub · bug, ui".
      header: string;
      title: string;
      excerpt: string;
      // "3 comments included"; null without any.
      comments: string | null;
      url: string;
    }
  | {
      kind: "review";
      // "Review feedback on #49, sent by Nest".
      header: string;
      // Each comment's place and author, such as "src/a.ts:12, octo", over its text.
      items: { place: string; text: string }[];
    };

// How much of an issue's description its bubble shows (NestKit's IssueBubble).
const EXCERPT_LINES = 3;
const EXCERPT_LIMIT = 240;

function excerptOf(body: string): string {
  const kept = body
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "")
    .slice(0, EXCERPT_LINES)
    .join("\n");
  return kept.length > EXCERPT_LIMIT ? `${kept.slice(0, EXCERPT_LIMIT)}…` : kept;
}

/**
 * A `session.user_message` payload's GitHub part from its `issue` or `review_feedback`
 * metadata, with the user's own words (an issue message's only), or null for any other.
 */
export function githubPartOf(p: JsonObject): { own: string; part: GitHubPart } | null {
  if (p.issue !== undefined && p.issue !== null) {
    const issue = obj(p.issue);
    const number = num(issue.number);
    const labels = list(issue.labels).filter((l): l is string => typeof l === "string");
    const marker = `Issue #${String(number)} from GitHub`;
    const comments = num(issue.comments);
    return {
      own: str(issue.user_text) ?? "",
      part: {
        kind: "issue",
        header: labels.length === 0 ? marker : `${marker} · ${labels.join(", ")}`,
        title: str(issue.title) ?? "",
        excerpt: excerptOf(str(issue.excerpt) ?? ""),
        comments:
          comments === 0
            ? null
            : `${String(comments)} ${comments === 1 ? "comment" : "comments"} included`,
        url: str(issue.url) ?? "",
      },
    };
  }
  if (p.review_feedback !== undefined && p.review_feedback !== null) {
    const feedback = obj(p.review_feedback);
    const items = list(feedback.comments).map((value, i) => {
      const c = obj(value);
      const place = commentPlace({
        id: String(i),
        path: str(c.path),
        line: typeof c.line === "number" ? c.line : null,
        outdated: c.outdated === true,
        body: "",
      });
      const author = str(c.author);
      return { place: author === null ? place : `${place}, ${author}`, text: str(c.body) ?? "" };
    });
    return {
      own: "",
      part: {
        kind: "review",
        header: `Review feedback on #${String(num(feedback.number))}, sent by Nest`,
        items,
      },
    };
  }
  return null;
}

/**
 * "Review on #49: changes requested, 3 comments. See Needs you", under the chat's latest
 * reply while its review comments wait (B101, NestKit's ReviewCommentsRequest.chatLine).
 */
export function reviewWaitingLine(approval: Approval): string {
  const { number, comments, changesRequested } = reviewCommentsOf(approval);
  const count = `${String(comments.length)} ${comments.length === 1 ? "comment" : "comments"}`;
  const what = changesRequested ? `changes requested, ${count}` : count;
  return `Review on #${String(number)}: ${what}. See Needs you`;
}
