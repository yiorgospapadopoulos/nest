import type { Element, ElementContent } from "hast";
import { memo, use, useEffect, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components, type Options } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { FILE_SCHEME, fromFileUrl, remarkChatText } from "./chatText.ts";
import { codeTokens } from "./codeColors.ts";
import { codeRef, lineIn, linkRef } from "./fileRefs.ts";
import { hasMath, useMath } from "./math.ts";
import {
  CopyTextContext,
  OpenFileContext,
  ReadFileContext,
  type OpenFile,
  type ReadFile,
} from "./openFile.ts";

// Messages and plans as Markdown (B144): CommonMark with tables, task lists, strikethrough
// and math. It builds React elements only: raw HTML shows as text and only web and file
// links open.

const SAFE_URL = /^https?:\/\//i;
const MATH = { singleDollarTextMath: false };

type Plugins = NonNullable<Options["remarkPlugins"]>;

/** Opens on a click, keeps its text selectable and copied as it is, and has no href to route. */
interface FileLinkProps {
  path: string;
  line: number | null;
  open: OpenFile;
  children: ReactNode;
}

function FileLink({ path, line, open, children }: FileLinkProps) {
  return (
    <a
      className="md-file"
      role="link"
      tabIndex={0}
      onClick={() => {
        open(path, line);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") open(path, line);
      }}
    >
      {children}
    </a>
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
  return (
    <div className="md-code">
      <pre>{parts}</pre>
      <CopyButton text={text} />
    </div>
  );
});

/** Copies a code block's text as written; says Copied for a moment. */
function CopyButton({ text }: { text: string }) {
  const copy = use(CopyTextContext);
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => {
      setDone(false);
    }, 1200);
    return () => {
      window.clearTimeout(timer);
    };
  }, [done]);
  return (
    <button
      className="md-copy"
      aria-label="Copy code"
      onClick={() => {
        void copy(text).then(() => {
          setDone(true);
        });
      }}
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

/** An image from the chat's folder, read through the daemon. */
function LocalImage({ path, alt, read }: { path: string; alt: string; read: ReadFile }) {
  const [url, setUrl] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    let made: string | null = null;
    void read(path).then((blob) => {
      if (!live) return;
      made = blob === null ? null : URL.createObjectURL(blob);
      setUrl(made);
    });
    return () => {
      live = false;
      if (made !== null) URL.revokeObjectURL(made);
    };
  }, [path, read]);
  if (url === undefined) return <span className="md-img wait" aria-hidden="true" />;
  if (url === null) return <>{alt === "" ? path : alt}</>;
  return <img className="md-img" src={url} alt={alt} />;
}

/**
 * A picture from the web loads only on a click (D173): its address is the agent's, and could
 * carry what it read to the site, so nothing is fetched until the user asks.
 */
function WebImage({ url, alt }: { url: string; alt: string }) {
  const [shown, setShown] = useState(false);
  if (shown) {
    return <img className="md-img" src={url} alt={alt} referrerPolicy="no-referrer" />;
  }
  return (
    <button
      className="md-imgask"
      title={url}
      onClick={() => {
        setShown(true);
      }}
    >
      Show picture from {new URL(url).host}
    </button>
  );
}

function textOf(node: ElementContent): string {
  if (node.type === "text") return node.value;
  return node.type === "element" ? node.children.map(textOf).join("") : "";
}

function language(code: Element): string | null {
  const names = code.properties.className;
  const found = Array.isArray(names)
    ? names.find((name) => typeof name === "string" && name.startsWith("language-"))
    : undefined;
  return typeof found === "string" ? found.slice("language-".length) : null;
}

function alignOf(node: Element | undefined): string | undefined {
  const align = node?.properties.align;
  return align === "right" ? "r" : align === "center" ? "c" : undefined;
}

function components(open: OpenFile | null, read: ReadFile | null): Components {
  return {
    // Inside a card that already sits under page and section headings.
    h1: ({ children }) => <h3>{children}</h3>,
    h2: ({ children }) => <h4>{children}</h4>,
    h3: ({ children }) => <h5>{children}</h5>,
    h4: ({ children }) => <h6>{children}</h6>,
    h5: ({ children }) => <h6>{children}</h6>,
    h6: ({ children }) => <h6>{children}</h6>,
    a: ({ href = "", children }) => {
      if (href.startsWith(FILE_SCHEME)) {
        const { path, line } = fromFileUrl(href);
        return open === null ? (
          children
        ) : (
          <FileLink path={path} line={line} open={open} children={children} />
        );
      }
      if (SAFE_URL.test(href)) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      }
      const path = open === null ? null : linkRef(href);
      // A link only to a web address or a file, otherwise its words alone.
      return path === null || open === null ? (
        children
      ) : (
        <FileLink path={path} line={lineIn(href)} open={open} children={children} />
      );
    },
    img: ({ src, alt = "" }) => {
      const url = typeof src === "string" ? src : "";
      if (SAFE_URL.test(url) && URL.canParse(url)) return <WebImage url={url} alt={alt} />;
      const path = linkRef(url);
      if (path !== null && read !== null) return <LocalImage path={path} alt={alt} read={read} />;
      return alt === "" ? url : alt;
    },
    code: ({ children }) => {
      const text = typeof children === "string" ? children : "";
      const path = open === null ? null : codeRef(text);
      const shown = <code>{children}</code>;
      return path === null || open === null ? (
        shown
      ) : (
        <FileLink path={path} line={lineIn(text)} open={open} children={shown} />
      );
    },
    pre: ({ node }) => {
      const code = node?.children[0];
      if (code?.type !== "element") return null;
      const text = textOf(code).replace(/\n$/, "");
      return <CodeBlock text={text} language={language(code)} />;
    },
    table: ({ children }) => (
      <div className="md-tw">
        <table>{children}</table>
      </div>
    ),
    th: ({ node, children }) => (
      <th scope="col" className={alignOf(node)}>
        {children}
      </th>
    ),
    td: ({ node, children }) => <td className={alignOf(node)}>{children}</td>,
    input: ({ checked }) => (
      <span
        className={checked === true ? "md-box on" : "md-box"}
        role="img"
        aria-label={checked === true ? "Done" : "Not done"}
      />
    ),
  };
}

function keep(url: string): string {
  return url.startsWith(FILE_SCHEME) ? url : defaultUrlTransform(url);
}

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const open = use(OpenFileContext);
  const read = use(ReadFileContext);
  const katex = useMath(hasMath(text));
  const shown = useMemo(() => components(open, read), [open, read]);
  const remark = useMemo<Plugins>(
    () => [remarkGfm, [remarkMath, MATH], [remarkChatText, { files: open !== null }]],
    [open],
  );
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={remark}
        rehypePlugins={katex === null ? [] : [katex]}
        components={shown}
        urlTransform={keep}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
