// Splits markdown into blocks for Markdown.tsx. Lists stay flat, each entry with its depth;
// what sits under an item (a code fence, a table, another paragraph) is an entry of its own.

export type Align = "r" | "c" | undefined;

export type ListEntry =
  | { kind: "item"; marker: string; task: boolean | null; depth: number; text: string }
  | { kind: "more"; marker: string; depth: number; blocks: Block[] };

export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; entries: ListEntry[] }
  // `language`: what the fence's opening line says, for colouring.
  | { kind: "pre"; text: string; language: string | null }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "table"; aligns: Align[]; header: string[]; rows: string[][] }
  | { kind: "rule" };

const FENCE = /^\s*(?:`{3,}|~{3,})/;
const HEADING = /^#{1,6}(?=\s)/;
const RULE = /^\s*([-*_])(?:\s*\1){2,}\s*$/;
const ITEM = /^\s*(?:[-*+]|\d+[.)])\s+/;
const TASK = /^\[([ xX])\](?:\s+|$)/;
const QUOTE = /^ {0,3}>/;
const QUOTE_MARKS = /^(?: {0,3}>[ \t]?)+/;
const PIPE = /(?:^|[^\\])\|/;
const DELIMITER_CELL = /^:?-+:?$/;
const MAX_DEPTH = 3;

export function parse(markdown: string): Block[] {
  return blocksOf(markdown.replace(/\r\n?/g, "\n").split("\n"));
}

function blocksOf(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let at = 0;
  while (at < lines.length) {
    const line = lines[at] ?? "";
    if (!line.trim()) {
      at += 1;
      continue;
    }
    const next = lines[at + 1] ?? "";
    let found: [Block, number];
    if (FENCE.test(line)) found = fenced(lines, at);
    else if (HEADING.test(line)) found = [headingOf(line), at + 1];
    else if (RULE.test(line)) found = [{ kind: "rule" }, at + 1];
    else if (QUOTE.test(line)) found = quoted(lines, at);
    else if (ITEM.test(line)) found = listed(lines, at);
    else if (opensTable(line, next)) found = table(lines, at);
    else found = paragraph(lines, at);
    blocks.push(found[0]);
    at = found[1];
  }
  return blocks;
}

function indentOf(line: string): number {
  let column = 0;
  for (const char of line) {
    if (char === " ") column += 1;
    else if (char === "\t") column += 4;
    else break;
  }
  return column;
}

/** The line without up to `columns` of its leading space. */
function dedent(line: string, columns: number): string {
  let column = 0;
  let at = 0;
  while (column < columns) {
    const char = line.charAt(at);
    if (char === " ") column += 1;
    else if (char === "\t") column += 4;
    else break;
    at += 1;
  }
  return line.slice(at);
}

/** Whether a line ends the text before it. */
function startsBlock(line: string, next: string): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    QUOTE.test(line) ||
    ITEM.test(line) ||
    opensTable(line, next)
  );
}

function headingOf(line: string): Block {
  const marks = HEADING.exec(line)?.[0].length ?? 1;
  const text = line
    .slice(marks)
    .trim()
    .replace(/\s+#+$/, "");
  return { kind: "heading", level: marks, text };
}

function paragraph(lines: string[], start: number): [Block, number] {
  const text = [(lines[start] ?? "").trim()];
  let at = start + 1;
  for (; at < lines.length; at += 1) {
    const line = lines[at] ?? "";
    if (!line.trim() || startsBlock(line, lines[at + 1] ?? "")) break;
    text.push(line.trim());
  }
  return [{ kind: "paragraph", text: text.join(" ") }, at];
}

/** A code block, its lines without the fence's indent; unclosed, it runs to the end. */
function fenced(lines: string[], start: number): [Block, number] {
  const open = lines[start] ?? "";
  const close = FENCE.exec(open)?.[0].trim() ?? "";
  const indent = indentOf(open);
  const language = open.trim().slice(close.length).trim() || null;
  const code: string[] = [];
  for (let at = start + 1; at < lines.length; at += 1) {
    const line = lines[at] ?? "";
    if (line.trim().startsWith(close)) {
      return [{ kind: "pre", text: code.join("\n"), language }, at + 1];
    }
    code.push(dedent(line, indent));
  }
  return [{ kind: "pre", text: code.join("\n"), language }, lines.length];
}

// A quote inside a quote shows as one quote, which also keeps this from nesting endlessly.
function quoted(lines: string[], start: number): [Block, number] {
  const inner: string[] = [];
  let at = start;
  for (; at < lines.length && QUOTE.test(lines[at] ?? ""); at += 1) {
    inner.push((lines[at] ?? "").replace(QUOTE_MARKS, ""));
  }
  return [{ kind: "quote", blocks: blocksOf(inner) }, at];
}

function isItem(line: string): boolean {
  return ITEM.test(line) && !RULE.test(line);
}

interface Level {
  indent: number;
  marker: string;
}

/**
 * A list. An item's depth comes from the items around it, not from a fixed indent width:
 * an item goes under the nearest one whose marker it is indented past, so agents' 3 and 4
 * space sublists are one level deeper, as 2 space ones are.
 */
function listed(lines: string[], start: number): [Block, number] {
  const entries: ListEntry[] = [];
  const levels: Level[] = [];
  let at = start;
  while (at < lines.length) {
    const line = lines[at] ?? "";
    if (!line.trim()) {
      at += 1;
      continue;
    }
    const indent = indentOf(line);
    if (isItem(line)) {
      while ((levels.at(-1)?.indent ?? -1) >= indent) levels.pop();
      const entry = itemOf(line, levels.length);
      levels.push({ indent, marker: entry.marker });
      entries.push(entry);
      at += 1;
      continue;
    }
    const last = entries.at(-1);
    const gap = !(lines[at - 1] ?? "").trim();
    const flush = line.trimStart();
    if (!gap && last?.kind === "item" && !startsBlock(flush, (lines[at + 1] ?? "").trimStart())) {
      last.text += ` ${line.trim()}`;
      at += 1;
      continue;
    }
    const owner = levels.findLastIndex((level) => level.indent < indent);
    if (owner === -1) break;
    levels.length = owner + 1;
    const { body, next } = underItem(lines, at, levels[owner]?.indent ?? 0);
    entries.push({
      kind: "more",
      marker: levels[owner]?.marker ?? "",
      depth: Math.min(MAX_DEPTH, owner),
      blocks: blocksOf(body),
    });
    at = next;
  }
  return [{ kind: "list", entries }, at];
}

function itemOf(line: string, depth: number): Extract<ListEntry, { kind: "item" }> {
  const lead = ITEM.exec(line)?.[0] ?? "";
  const marker = lead.trim();
  const text = line.slice(lead.length);
  const task = TASK.exec(text);
  return {
    kind: "item",
    marker: /\d/.test(marker) ? marker : "•",
    task: task === null ? null : task[1] !== " ",
    depth: Math.min(MAX_DEPTH, depth),
    text: task === null ? text : text.slice(task[0].length),
  };
}

/** The lines under an item, without their indent, up to the next item or less indented line. */
function underItem(
  lines: string[],
  start: number,
  floor: number,
): { body: string[]; next: number } {
  const indent = indentOf(lines[start] ?? "");
  const body: string[] = [];
  let close: string | null = null;
  let at = start;
  for (; at < lines.length; at += 1) {
    const line = lines[at] ?? "";
    if (close !== null) {
      if (line.trim().startsWith(close)) close = null;
    } else if (line.trim()) {
      if (indentOf(line) <= floor || isItem(line)) break;
      close = FENCE.exec(line)?.[0].trim() ?? null;
    }
    body.push(dedent(line, indent));
  }
  return { body, next: at };
}

/** Whether these two lines start a table: its header and a delimiter of as many columns. */
function opensTable(header: string, delimiter: string): boolean {
  if (!delimiter.includes("-") || !PIPE.test(header)) return false;
  return alignsOf(delimiter)?.length === cellsOf(header).length;
}

function alignsOf(delimiter: string): Align[] | null {
  if (!delimiter.includes("|")) return null;
  const cells = cellsOf(delimiter);
  if (cells.length === 0 || !cells.every((cell) => DELIMITER_CELL.test(cell))) return null;
  return cells.map((cell) => {
    if (cell.endsWith(":")) return cell.startsWith(":") ? "c" : "r";
    return undefined;
  });
}

function table(lines: string[], start: number): [Block, number] {
  const header = cellsOf(lines[start] ?? "");
  const aligns = alignsOf(lines[start + 1] ?? "") ?? [];
  const rows: string[][] = [];
  let at = start + 2;
  for (; at < lines.length; at += 1) {
    const line = lines[at] ?? "";
    if (!PIPE.test(line) || startsBlock(line, lines[at + 1] ?? "")) break;
    const cells = cellsOf(line);
    rows.push(header.map((_, index) => cells[index] ?? ""));
  }
  return [{ kind: "table", aligns, header, rows }, at];
}

/**
 * A row's cells. A pipe splits a cell unless it is escaped or inside a code span. GFM does
 * split inside code, but agents write `curl x | sh` in tables, escaped or not. In code an
 * escaped pipe loses its backslash here, since inline code reads no escapes.
 */
function cellsOf(row: string): string[] {
  const text = row.trim();
  const cells: string[] = [];
  let cell = "";
  let at = text.startsWith("|") ? 1 : 0;
  while (at < text.length) {
    const char = text.charAt(at);
    if (char === "\\") {
      cell += text.slice(at, at + 2);
      at += 2;
    } else if (char === "`") {
      const end = codeEnd(text, at);
      cell += text.slice(at, end).replaceAll("\\|", "|");
      at = end;
    } else if (char === "|") {
      cells.push(cell.trim());
      cell = "";
      at += 1;
    } else {
      cell += char;
      at += 1;
    }
  }
  if (cell.trim()) cells.push(cell.trim());
  return cells;
}

/** Where the code span opening at `start` ends; past its backticks alone when it never closes. */
function codeEnd(text: string, start: number): number {
  let size = 0;
  while (text.charAt(start + size) === "`") size += 1;
  const from = start + size;
  for (const run of text.slice(from).matchAll(/`+/g)) {
    if (run[0].length === size) return from + run.index + size;
  }
  return from;
}
