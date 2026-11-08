import { Fragment, memo, use, useMemo, type ReactNode } from "react";
import { codeTokens } from "./codeColors.ts";
import { codeRef, fileRefsIn, linkRef } from "./fileRefs.ts";
import { parse, type Block, type ListEntry } from "./markdownBlocks.ts";
import { OpenFileContext, type OpenFile } from "./openFile.ts";

// A small markdown reader for messages and plans. It builds React elements only, never raw
// HTML.

// A marked span's text: an escaped character in it is not its closing mark.
const SPAN = String.raw`(?:\\.|[^\\\n])+?`;
// In order of precedence, each with one capture but the links' two and the bare address's
// none: an escape, inline code, bold, italic (not inside words), strikethrough, a link or an
// image, an address in angle brackets, and a bare address.
const INLINE = new RegExp(
  [
    /\\([!-/:-@[-`{-~])/.source,
    /`([^`]+)`/.source,
    String.raw`\*\*(${SPAN})\*\*`,
    `__(${SPAN})__`,
    String.raw`\*(?!\s)(${SPAN})\*`,
    String.raw`\b_(?!\s)(${SPAN})_\b`,
    `~~(?!\\s)(${SPAN})~~`,
    // A link, or an image, shown as a link: nothing is loaded from what an agent wrote.
    /!?\[([^\]]*)\]\(([^)\s]+)\)/.source,
    /<(https?:\/\/[^\s<>]+)>/.source,
    /\bhttps?:\/\/[^\s<>]+/.source,
  ].join("|"),
  "gi",
);
const SAFE_URL = /^https?:\/\//i;
const WEB_ADDRESS = /^https?:\/\/./i;
const TRAILING = /[?!.,:;*_~'"]$/;

function count(text: string, char: string): number {
  return text.split(char).length - 1;
}

/** A bare address without the punctuation that ends the sentence around it. */
function addressIn(found: string): string {
  let url = found;
  for (;;) {
    const unmatched = url.endsWith(")") && count(url, ")") > count(url, "(");
    if (!unmatched && !TRAILING.test(url)) return url;
    url = url.slice(0, -1);
  }
}

function link(key: number, url: string, label: ReactNode): ReactNode {
  return (
    <a key={key} href={url} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
}

/** Opens on a click, keeps its text selectable and copied as it is, and has no href to route. */
function fileLink(key: number, path: string, label: ReactNode, open: OpenFile): ReactNode {
  return (
    <a
      key={key}
      className="md-file"
      role="link"
      tabIndex={0}
      onClick={() => {
        open(path);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") open(path);
      }}
    >
      {label}
    </a>
  );
}

/** Plain text, with what names a file as links. */
function plain(text: string, offset: number, open: OpenFile | null): ReactNode[] {
  if (open === null) return [text];
  const out: ReactNode[] = [];
  let last = 0;
  for (const ref of fileRefsIn(text)) {
    if (ref.start > last) out.push(text.slice(last, ref.start));
    out.push(fileLink(offset + ref.start, ref.path, text.slice(ref.start, ref.end), open));
    last = ref.end;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// `links` is off inside a link's label, as a link cannot hold another.
function inline(text: string, open: OpenFile | null, links = true): ReactNode[] {
  const files = links ? open : null;
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const [whole, escaped, code, bold1, bold2, em1, em2, struck, label, url, auto] = match;
    if (match.index > last) out.push(...plain(text.slice(last, match.index), last, files));
    const key = match.index;
    const strong = bold1 ?? bold2;
    const em = em1 ?? em2;
    last = match.index + whole.length;
    if (escaped !== undefined) out.push(escaped);
    else if (code !== undefined) {
      const path = files === null ? null : codeRef(code);
      const shown = <code key={key}>{code}</code>;
      out.push(files !== null && path !== null ? fileLink(key, path, shown, files) : shown);
    } else if (strong !== undefined) {
      out.push(<strong key={key}>{inline(strong, open, links)}</strong>);
    } else if (em !== undefined) out.push(<em key={key}>{inline(em, open, links)}</em>);
    else if (struck !== undefined) out.push(<del key={key}>{inline(struck, open, links)}</del>);
    else if (label !== undefined) {
      // A link only to a web address or a file, otherwise its label alone; an image with no
      // words is named by its address.
      const shown = inline(label === "" ? (url ?? "") : label, open, false);
      const path = files === null || url === undefined ? null : linkRef(url);
      if (url !== undefined && SAFE_URL.test(url)) out.push(link(key, url, shown));
      else if (files !== null && path !== null) out.push(fileLink(key, path, shown, files));
      else out.push(<Fragment key={key}>{shown}</Fragment>);
    } else if (auto !== undefined) {
      out.push(links ? link(key, auto, auto) : auto);
    } else {
      const address = addressIn(whole);
      if (links && WEB_ADDRESS.test(address)) {
        out.push(link(key, address, address));
        // What was left off goes on as text.
        last = match.index + address.length;
      } else {
        out.push(whole);
      }
    }
  }
  if (last < text.length) out.push(...plain(text.slice(last), last, files));
  return out;
}

function heading(level: number, text: string, key: number, open: OpenFile | null): ReactNode {
  // Inside a card that already sits under page and section headings.
  const content = inline(text, open);
  if (level === 1) return <h3 key={key}>{content}</h3>;
  if (level === 2) return <h4 key={key}>{content}</h4>;
  if (level === 3) return <h5 key={key}>{content}</h5>;
  return <h6 key={key}>{content}</h6>;
}

function entry(item: ListEntry, key: number, open: OpenFile | null): ReactNode {
  if (item.kind === "more") {
    return (
      <li key={key} className={`d${String(item.depth)} more`}>
        <span className="mk sp" aria-hidden="true">
          {item.marker}
        </span>
        <div className="md-in">{blocks(item.blocks, open)}</div>
      </li>
    );
  }
  return (
    <li key={key} className={`d${String(item.depth)}`}>
      {item.task === null ? (
        <span className="mk" aria-hidden="true">
          {item.marker}
        </span>
      ) : (
        <span
          className={item.task ? "md-box on" : "md-box"}
          role="img"
          aria-label={item.task ? "Done" : "Not done"}
        />
      )}
      <span>{inline(item.text, open)}</span>
    </li>
  );
}

function table(
  block: Extract<Block, { kind: "table" }>,
  key: number,
  open: OpenFile | null,
): ReactNode {
  return (
    <div key={key} className="md-tw">
      <table>
        <thead>
          <tr>
            {block.header.map((cell, index) => (
              <th key={index} scope="col" className={block.aligns[index]}>
                {inline(cell, open)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, index) => (
                <td key={index} className={block.aligns[index]}>
                  {inline(cell, open)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Code with its colours as spans of the same text, so it selects and copies as written. */
const CodeBlock = memo(function CodeBlock({
  text,
  language,
}: {
  text: string;
  language: string | null;
}) {
  const parts = useMemo(() => {
    const out: ReactNode[] = [];
    let last = 0;
    for (const { kind, start, end } of codeTokens(language, text)) {
      if (start > last) out.push(text.slice(last, start));
      out.push(
        <span key={start} className={`code-${kind}`}>
          {text.slice(start, end)}
        </span>,
      );
      last = end;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }, [text, language]);
  return <pre>{parts}</pre>;
});

function render(block: Block, key: number, open: OpenFile | null): ReactNode {
  switch (block.kind) {
    case "heading":
      return heading(block.level, block.text, key, open);
    case "paragraph":
      return <p key={key}>{inline(block.text, open)}</p>;
    case "list":
      return <ul key={key}>{block.entries.map((item, index) => entry(item, index, open))}</ul>;
    case "pre":
      return <CodeBlock key={key} text={block.text} language={block.language} />;
    case "quote":
      return <blockquote key={key}>{blocks(block.blocks, open)}</blockquote>;
    case "table":
      return table(block, key, open);
    case "rule":
      return <hr key={key} />;
  }
}

function blocks(list: Block[], open: OpenFile | null): ReactNode[] {
  return list.map((block, index) => render(block, index, open));
}

export function Markdown({ text }: { text: string }) {
  const open = use(OpenFileContext);
  return <div className="md">{blocks(parse(text), open)}</div>;
}
