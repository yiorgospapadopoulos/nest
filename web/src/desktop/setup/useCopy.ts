import { useEffect, useState } from "react";

const COPIED_MS = 1500;

/** Copies `text`; `copied` holds for a moment after. */
export function useCopy(text: string) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => {
      setCopied(false);
    }, COPIED_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [copied]);
  return {
    copied,
    copy: () => {
      void navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
      });
    },
  };
}
