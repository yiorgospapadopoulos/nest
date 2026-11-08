import { useEffect, useState } from "react";
import type { Options } from "react-markdown";

type Pluggable = NonNullable<Options["rehypePlugins"]>[number];

// KaTeX and its fonts load only for a message with math (B144).
let loaded: Pluggable | null = null;
let loading: Promise<void> | null = null;

function load(): Promise<void> {
  loading ??= Promise.all([import("rehype-katex"), import("katex/dist/katex.min.css")]).then(
    ([katex]) => {
      loaded = katex.default;
    },
  );
  return loading;
}

/** Math is `$$` around it, inline or on its own lines; a single `$` is a dollar. */
export function hasMath(text: string): boolean {
  return text.includes("$$");
}

/** The plugin that draws math, once loaded; null until then, and for text without math. */
export function useMath(wanted: boolean): Pluggable | null {
  const [, setReady] = useState(loaded !== null);
  useEffect(() => {
    if (!wanted || loaded !== null) return;
    let live = true;
    void load().then(() => {
      if (live) setReady(true);
    });
    return () => {
      live = false;
    };
  }, [wanted]);
  return wanted ? loaded : null;
}
