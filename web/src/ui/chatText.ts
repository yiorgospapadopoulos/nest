import type { Nodes, Parent, Root, RootContent } from "mdast";
import { fileRefsIn, lineIn } from "./fileRefs.ts";

// A link to a file the text names, made here and opened by whoever shows the message:
// `nest-file:<path>`, then `#<line>` with a line.
export const FILE_SCHEME = "nest-file:";

export function fileUrl(path: string, line: number | null): string {
  return FILE_SCHEME + encodeURIComponent(path) + (line === null ? "" : `#${String(line)}`);
}

export function fromFileUrl(url: string): { path: string; line: number | null } {
  const [path = "", line] = url.slice(FILE_SCHEME.length).split("#");
  return { path: decodeURIComponent(path), line: line === undefined ? null : Number(line) };
}

// Where a paragraph can stand, so raw HTML there becomes one.
const FLOW = new Set(["root", "blockquote", "listItem", "footnoteDefinition"]);

/**
 * How a chat reads Markdown, before it is drawn: a wrapped line goes on as a space, raw
 * HTML shows as the text it is (nothing an agent writes becomes a page element), and with
 * `files` what names a file links to it.
 */
export function remarkChatText({ files }: { files: boolean }) {
  return (tree: Root) => {
    walk(tree, files);
  };
}

function walk(node: Parent, files: boolean): void {
  // A link cannot hold another.
  const linking = files && node.type !== "link" && node.type !== "linkReference";
  const out: RootContent[] = [];
  for (const child of node.children) {
    if (child.type === "text") out.push(...split(child.value.replace(/\r?\n/g, " "), linking));
    else if (child.type === "html") {
      const text = { type: "text" as const, value: child.value };
      out.push(FLOW.has(node.type) ? { type: "paragraph", children: [text] } : text);
    } else {
      if ("children" in child) walk(child, linking);
      out.push(child);
    }
  }
  (node as { children: Nodes[] }).children = out;
}

function split(value: string, files: boolean): RootContent[] {
  if (!files) return [{ type: "text", value }];
  const out: RootContent[] = [];
  let last = 0;
  for (const ref of fileRefsIn(value)) {
    if (ref.start > last) out.push({ type: "text", value: value.slice(last, ref.start) });
    const shown = value.slice(ref.start, ref.end);
    out.push({
      type: "link",
      url: fileUrl(ref.path, lineIn(shown)),
      children: [{ type: "text", value: shown }],
    });
    last = ref.end;
  }
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}
