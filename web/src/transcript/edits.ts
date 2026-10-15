import { list, obj, str } from "../api/payloads.ts";
import type { JsonObject } from "../api/types.ts";

/** A line of an edit's diff; a gap separates the edits of a MultiEdit. */
export interface DiffLine {
  kind: "add" | "del" | "ctx" | "gap";
  text: string;
}

/** What an edit tool call changes, as Claude's apps show it inline (B59). */
export interface EditDiff {
  added: number;
  removed: number;
  lines: DiffLine[];
}

// Above this many line pairs to compare, a change shows as removed then added.
const MATCH_LIMIT = 250_000;

/** The text's lines; a final newline ends the last line rather than starting another. */
function linesOf(text: string): string[] {
  if (text === "") return [];
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

/** The lines of `before` and `after`, kept, removed or added, by longest common subsequence. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = linesOf(before);
  const b = linesOf(after);
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (
    tail < a.length - head &&
    tail < b.length - head &&
    a[a.length - 1 - tail] === b[b.length - 1 - tail]
  ) {
    tail += 1;
  }
  const context = (text: string): DiffLine => ({ kind: "ctx", text });
  return [
    ...a.slice(0, head).map(context),
    ...middle(a.slice(head, a.length - tail), b.slice(head, b.length - tail)),
    ...a.slice(a.length - tail).map(context),
  ];
}

/** The changed middle of a diff. */
function middle(a: string[], b: string[]): DiffLine[] {
  const removed = (text: string): DiffLine => ({ kind: "del", text });
  const added = (text: string): DiffLine => ({ kind: "add", text });
  if (a.length * b.length > MATCH_LIMIT) return [...a.map(removed), ...b.map(added)];
  // At i * width + j: the longest common subsequence of a[i:] and b[j:].
  const width = b.length + 1;
  const lengths = new Uint32Array((a.length + 1) * width);
  const at = (i: number, j: number) => Number(lengths[i * width + j]);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lengths[i * width + j] =
        a[i] === b[j] ? at(i + 1, j + 1) + 1 : Math.max(at(i + 1, j), at(i, j + 1));
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      out.push({ kind: "ctx", text: String(a[i]) });
      i += 1;
      j += 1;
    } else if (j < b.length && (i === a.length || at(i, j + 1) > at(i + 1, j))) {
      out.push(added(String(b[j])));
      j += 1;
    } else {
      out.push(removed(String(a[i])));
      i += 1;
    }
  }
  return out;
}

function counted(lines: DiffLine[]): EditDiff | null {
  const added = lines.filter((line) => line.kind === "add").length;
  const removed = lines.filter((line) => line.kind === "del").length;
  return added + removed === 0 ? null : { added, removed, lines };
}

function replaced(edit: JsonObject): DiffLine[] | null {
  const before = str(edit.old_string);
  const after = str(edit.new_string);
  return before === null || after === null ? null : lineDiff(before, after);
}

const allAdded = (text: string): DiffLine[] =>
  linesOf(text).map((line) => ({ kind: "add", text: line }));

/**
 * The diff an edit tool call makes, built from its input: an Edit's old and new text, a
 * MultiEdit's edits, a Write's content or a NotebookEdit's new cell as added. Null for
 * other tools and for inputs without the text.
 */
export function editDiff(name: string, input: JsonObject): EditDiff | null {
  switch (name) {
    case "Edit": {
      const lines = replaced(input);
      return lines === null ? null : counted(lines);
    }
    case "MultiEdit": {
      const edits = list(input.edits)
        .map((edit) => replaced(obj(edit)))
        .filter((lines) => lines !== null);
      const gap: DiffLine = { kind: "gap", text: "" };
      return counted(edits.flatMap((lines, index) => (index === 0 ? lines : [gap, ...lines])));
    }
    case "Write": {
      const content = str(input.content);
      return content === null ? null : counted(allAdded(content));
    }
    case "NotebookEdit": {
      const source = str(input.new_source);
      return source === null || input.edit_mode === "delete" ? null : counted(allAdded(source));
    }
    default:
      return null;
  }
}
