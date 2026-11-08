import { useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import { codeTokens } from "./codeColors.ts";
import { extensionOf } from "./fileKind.ts";

/** Text in numbered lines, coloured where its language is known, the named line marked. */
export function TextLines({
  text,
  name,
  line,
  cut,
}: {
  text: string;
  name: string;
  line: number | null;
  cut: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => {
    const tokens = codeTokens(extensionOf(name), text);
    const lines: ReactNode[][] = [[]];
    let at = 0;
    const put = (end: number, kind: string | null) => {
      while (at < end) {
        const stop = text.indexOf("\n", at);
        const until = stop === -1 || stop >= end ? end : stop;
        if (until > at) {
          const part = text.slice(at, until);
          lines.at(-1)?.push(
            kind === null ? (
              part
            ) : (
              <span key={at} className={`code-${kind}`}>
                {part}
              </span>
            ),
          );
        }
        at = until;
        if (until === stop) {
          lines.push([]);
          at += 1;
        }
      }
    };
    for (const token of tokens) {
      put(token.start, null);
      put(token.end, token.kind);
    }
    put(text.length, null);
    // Text that ends with a line break has no line after it.
    return lines.length > 1 && lines.at(-1)?.length === 0 ? lines.slice(0, -1) : lines;
  }, [text, name]);

  useLayoutEffect(() => {
    if (line === null) return;
    box.current?.querySelector(".fv-on")?.scrollIntoView({ block: "center" });
  }, [line, rows]);

  return (
    <div ref={box} className="fv-text md">
      <pre>
        {rows.map((parts, index) => (
          <span key={index} className={index + 1 === line ? "fv-ln fv-on" : "fv-ln"}>
            <span className="fv-no" aria-hidden="true">
              {index + 1}
            </span>
            {parts}
            {"\n"}
          </span>
        ))}
      </pre>
      {cut && <p className="fv-note">Showing the first part. Save the file to see all of it.</p>}
    </div>
  );
}
