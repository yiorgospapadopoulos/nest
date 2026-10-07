import type { ReactNode } from "react";

// A small markdown reader for plans: headings, paragraphs, lists, code, tables as written,
// rules and the common inline marks. It builds React elements only, never raw HTML.

interface ListItem {
  marker: string;
  depth: number;
  text: string;
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: ListItem[] }
  | { kind: "pre"; text: string }
  | { kind: "rule" };

const FENCE = /^\s*(?:`{3,}|~{3,})/;
const HEADING = /^#{1,6}(?=\s)/;
const RULE = /^\s*([-*_])(?:\s*\1){2,}\s*$/;
const ITEM = /^\s*(?:[-*+]|\d+[.)])\s+/;
const MAX_DEPTH = 3;

function parse(markdown: string): Block[] {
  const blocks: Block[] = [];
  // The block that a following line may continue: a blank line ends a paragraph or a
  // table, while a list goes on with its next item.
  let open: Extract<Block, { kind: "paragraph" | "list" | "pre" }> | null = null;
  let gap = false;
  // Inside a fenced code block: the fence that closes it, and its lines so far.
  let fence: string | null = null;
  let code: string[] = [];
  const add = <T extends Block>(block: T): T => {
    blocks.push(block);
    gap = false;
    return block;
  };
  for (const line of markdown.replace(/\r\n?/g, "\n").split("\n")) {
    if (fence !== null) {
      if (line.trim().startsWith(fence)) {
        add({ kind: "pre", text: code.join("\n") });
        fence = null;
      } else {
        code.push(line);
      }
      continue;
    }
    const opening = FENCE.exec(line);
    if (opening !== null) {
      fence = opening[0].trim();
      code = [];
      open = null;
      continue;
    }
    if (!line.trim()) {
      gap = true;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading !== null) {
      const text = line
        .slice(heading[0].length)
        .trim()
        .replace(/\s+#+$/, "");
      add({ kind: "heading", level: heading[0].length, text });
      open = null;
      continue;
    }
    if (RULE.test(line)) {
      add({ kind: "rule" });
      open = null;
      continue;
    }
    const item = ITEM.exec(line);
    if (item !== null) {
      const marker = item[0].trim();
      const entry: ListItem = {
        marker: /\d/.test(marker) ? marker : "•",
        depth: Math.min(MAX_DEPTH, Math.floor((line.length - line.trimStart().length) / 2)),
        text: line.slice(item[0].length),
      };
      if (open?.kind === "list") {
        open.items.push(entry);
        gap = false;
      } else {
        open = add({ kind: "list", items: [entry] });
      }
      continue;
    }
    if (line.trimStart().startsWith("|")) {
      if (open?.kind === "pre" && !gap) open.text += `\n${line}`;
      else open = add({ kind: "pre", text: line });
      continue;
    }
    const text = line.trim();
    if (open?.kind === "list" && !gap) {
      open.items[open.items.length - 1] = continued(open.items, text);
    } else if (open?.kind === "paragraph" && !gap) {
      open.text += ` ${text}`;
    } else {
      open = add({ kind: "paragraph", text });
    }
  }
  // A code block nobody closed runs to the end.
  if (fence !== null) blocks.push({ kind: "pre", text: code.join("\n") });
  return blocks;
}

/** The list's last item with a wrapped line added. */
function continued(items: ListItem[], text: string): ListItem {
  const [last] = items.slice(-1) as [ListItem];
  return { ...last, text: `${last.text} ${text}` };
}

// Inline code, bold, italic (not inside words) and links, in that order of precedence.
const INLINE =
  /`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|\*(?!\s)(.+?)\*|\b_(?!\s)(.+?)_\b|\[([^\]]+)\]\(([^)\s]+)\)/g;
const SAFE_URL = /^https?:\/\//i;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const [whole, code, bold1, bold2, em1, em2] = match;
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = match.index;
    const strong = bold1 ?? bold2;
    const em = em1 ?? em2;
    if (code !== undefined) out.push(<code key={key}>{code}</code>);
    else if (strong !== undefined) out.push(<strong key={key}>{inline(strong)}</strong>);
    else if (em !== undefined) out.push(<em key={key}>{inline(em)}</em>);
    else {
      // "[label](url)": a link only to a web address, otherwise its label alone.
      const middle = whole.indexOf("](");
      const label = whole.slice(1, middle);
      const url = whole.slice(middle + 2, -1);
      if (SAFE_URL.test(url)) {
        out.push(
          <a key={key} href={url} target="_blank" rel="noopener noreferrer">
            {inline(label)}
          </a>,
        );
      } else {
        out.push(...inline(label));
      }
    }
    last = match.index + whole.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function heading(level: number, text: string, key: number): ReactNode {
  // Inside a card that already sits under page and section headings.
  const content = inline(text);
  if (level === 1) return <h3 key={key}>{content}</h3>;
  if (level === 2) return <h4 key={key}>{content}</h4>;
  if (level === 3) return <h5 key={key}>{content}</h5>;
  return <h6 key={key}>{content}</h6>;
}

function render(block: Block, key: number): ReactNode {
  switch (block.kind) {
    case "heading":
      return heading(block.level, block.text, key);
    case "paragraph":
      return <p key={key}>{inline(block.text)}</p>;
    case "list":
      return (
        <ul key={key}>
          {block.items.map((item, index) => (
            <li key={index} className={`d${String(item.depth)}`}>
              <span className="mk" aria-hidden="true">
                {item.marker}
              </span>
              <span>{inline(item.text)}</span>
            </li>
          ))}
        </ul>
      );
    case "pre":
      return <pre key={key}>{block.text}</pre>;
    case "rule":
      return <hr key={key} />;
  }
}

export function Markdown({ text }: { text: string }) {
  return <div className="md">{parse(text).map(render)}</div>;
}
