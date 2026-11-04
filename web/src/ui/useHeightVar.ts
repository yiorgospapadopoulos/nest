import { useLayoutEffect, useRef } from "react";

/**
 * For something floating over its parent's content: keeps the CSS variable `name` on the
 * parent at the element's height, so what scrolls under it can leave room to reach the end.
 */
export function useHeightVar(name: string) {
  const element = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const box = element.current;
    const parent = box?.parentElement;
    if (box === null || parent === null || parent === undefined) return;
    const observer = new ResizeObserver(() => {
      parent.style.setProperty(name, `${String(box.offsetHeight)}px`);
    });
    observer.observe(box);
    return () => {
      observer.disconnect();
      parent.style.removeProperty(name);
    };
  }, [name]);
  return element;
}
