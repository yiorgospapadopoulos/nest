// What menus and popovers share: their place next to what opened them, and how they go
// away (outside press, Escape and Ctrl+W through the overlay stack, the window losing
// focus or changing size, the user scrolling something under them).
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import { openOverlay } from "./overlays.ts";
import type { Size } from "./place.ts";

/**
 * Measures `ref`'s element and places it with `place`, again whenever its size changes;
 * hidden until it has its place, so it never shows at the wrong spot first.
 */
export function usePlaced(
  ref: RefObject<HTMLElement | null>,
  place: (size: Size, view: Size) => { left: number; top: number },
): CSSProperties {
  const [at, setAt] = useState<{ left: number; top: number } | null>(null);
  const latest = useRef(place);
  useLayoutEffect(() => {
    latest.current = place;
  });
  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const measure = () => {
      const next = latest.current(
        { width: element.offsetWidth, height: element.offsetHeight },
        { width: window.innerWidth, height: window.innerHeight },
      );
      setAt((before) =>
        before !== null && before.left === next.left && before.top === next.top ? before : next,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [ref]);
  return at === null ? { left: 0, top: 0, visibility: "hidden" } : { left: at.left, top: at.top };
}

interface Dismiss {
  // Whether a pointer press on this node is inside (it keeps the overlay open).
  inside: (target: Node) => boolean;
  onDismiss: () => void;
  // The outside press only closes, as a click outside an AppKit menu does nothing else.
  swallow: boolean;
}

/** Closes on a press outside, on the window's blur or resize, and on a wheel outside. */
export function useDismiss({ inside, onDismiss, swallow }: Dismiss): void {
  const latest = useRef({ inside, onDismiss });
  useLayoutEffect(() => {
    latest.current = { inside, onDismiss };
  });
  useEffect(() => {
    let swallowClick: ((event: MouseEvent) => void) | null = null;
    const stopSwallowing = () => {
      if (swallowClick !== null) window.removeEventListener("click", swallowClick, true);
      swallowClick = null;
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target === null || latest.current.inside(target)) return;
      if (swallow) {
        event.preventDefault();
        event.stopPropagation();
        swallowClick = (click: MouseEvent) => {
          click.preventDefault();
          click.stopPropagation();
          stopSwallowing();
        };
        window.addEventListener("click", swallowClick, true);
      }
      latest.current.onDismiss();
    };
    // The click of that press, if it comes, ends the swallowing; the next press does too,
    // since WebKitGTK does not always send one.
    const onNextPress = () => {
      stopSwallowing();
    };
    // Only the user's own scrolling outside closes it: a transcript that keeps to its end,
    // or a list measured again, scrolls by itself, and that closed a menu as it was used.
    const onWheel = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && latest.current.inside(target)) return;
      latest.current.onDismiss();
    };
    const onLeave = () => {
      latest.current.onDismiss();
    };
    // Resize events also come when nothing changed size (WebKitGTK sends some as windows
    // take and lose focus); only a real change closes it.
    let size = { width: window.innerWidth, height: window.innerHeight };
    const onResize = () => {
      const next = { width: window.innerWidth, height: window.innerHeight };
      if (next.width === size.width && next.height === size.height) return;
      size = next;
      latest.current.onDismiss();
    };
    // Registered after this press's own listeners ran, so the press that opened it does not
    // also close it.
    const timer = window.setTimeout(() => {
      document.addEventListener("pointerdown", onNextPress, true);
      document.addEventListener("pointerdown", onPointerDown, true);
    }, 0);
    document.addEventListener("wheel", onWheel, { capture: true, passive: true });
    window.addEventListener("blur", onLeave);
    window.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointerdown", onNextPress, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("wheel", onWheel, true);
      window.removeEventListener("blur", onLeave);
      window.removeEventListener("resize", onResize);
      // A swallow still waiting for its click stays until that click or the next press.
      if (swallowClick !== null) {
        const pending = swallowClick;
        const clear = () => {
          window.removeEventListener("click", pending, true);
          document.removeEventListener("pointerdown", clear, true);
        };
        document.addEventListener("pointerdown", clear, true);
      }
    };
  }, [swallow]);
}

/**
 * Takes the tooltip off what opened an overlay while the overlay is open. WebKitGTK shows
 * a `title` as a GTK tooltip window under the pointer, over the overlay's first rows, and
 * in Nest those windows draw blank: the first click on a row landed on the tooltip.
 */
export function useNoTooltip(owner: () => HTMLElement | null | undefined): void {
  const latest = useRef(owner);
  useLayoutEffect(() => {
    const element = latest.current();
    const title = element?.getAttribute("title");
    if (element == null || title == null) return;
    element.removeAttribute("title");
    return () => {
      if (!element.hasAttribute("title")) element.setAttribute("title", title);
    };
  }, []);
}

/**
 * The element really under a press or release. WebKitGTK sends a press that comes with no
 * pointer movement before it (a pointer that jumps there and presses at once, as touch,
 * tablets and accessibility tools do) to the element the pointer was last over, such as
 * the button that opened a menu; its position is right, so the element there is read.
 */
export function elementAt(event: { clientX: number; clientY: number; target: EventTarget | null }) {
  const at =
    typeof document.elementFromPoint === "function"
      ? document.elementFromPoint(event.clientX, event.clientY)
      : null;
  if (at !== null) return at;
  return event.target instanceof Element ? event.target : null;
}

/** Whether the event went to another element than the one under it (`elementAt`). */
export function misdirected(event: {
  clientX: number;
  clientY: number;
  target: EventTarget | null;
}) {
  const at = elementAt(event);
  return at !== null && event.target instanceof Node && !at.contains(event.target);
}

/** Stops the click that follows a press handled here, or the next press if none comes. */
export function swallowNextClick(): void {
  const swallow = (click: MouseEvent) => {
    click.preventDefault();
    click.stopPropagation();
    stop();
  };
  const stop = () => {
    window.removeEventListener("click", swallow, true);
    window.removeEventListener("pointerdown", stop, true);
  };
  window.addEventListener("click", swallow, true);
  // A later press ends it, so a click that never came takes nothing from it.
  window.setTimeout(() => {
    window.addEventListener("pointerdown", stop, true);
  }, 0);
}

const CONTROLS = "button, a[href], [role=menuitem], [role=option]";

/**
 * A press and release inside `box` that the web view sent to another element
 * (`elementAt`): they go no further, and the control under them is clicked. Used by
 * popovers, whose rows are plain buttons.
 */
export function useMisdirectedPress(box: () => HTMLElement | null): void {
  const latest = useRef(box);
  useLayoutEffect(() => {
    latest.current = box;
  });
  useEffect(() => {
    let pressed: Element | null = null;
    const inside = (event: PointerEvent) => {
      const element = latest.current();
      const at = elementAt(event);
      return element !== null && at !== null && element.contains(at) && misdirected(event)
        ? at
        : null;
    };
    const down = (event: PointerEvent) => {
      pressed = event.button === 0 ? inside(event) : null;
      if (pressed === null) return;
      event.preventDefault();
      event.stopPropagation();
    };
    const up = (event: PointerEvent) => {
      const was = pressed;
      pressed = null;
      if (was === null) return;
      event.preventDefault();
      event.stopPropagation();
      const control = elementAt(event)?.closest<HTMLElement>(CONTROLS);
      if (control != null && control === was.closest(CONTROLS)) control.click();
      // The web view's own click of this press would go to the element it was sent to.
      swallowNextClick();
    };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("pointerup", up, true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("pointerup", up, true);
    };
  }, []);
}

/** Takes part in the window's Escape and Ctrl+W order while mounted. */
export function useOverlay(close: () => void): void {
  const latest = useRef(close);
  useLayoutEffect(() => {
    latest.current = close;
  });
  useEffect(
    () =>
      openOverlay(() => {
        latest.current();
      }),
    [],
  );
}

/** The element focused before an overlay opened gets it back when the overlay goes. */
export function useRestoreFocus(): void {
  // Read while rendering, before the overlay takes the focus.
  const [before] = useState(() => document.activeElement);
  useEffect(() => {
    return () => {
      if (before instanceof HTMLElement && before.isConnected)
        before.focus({ preventScroll: true });
    };
  }, [before]);
}
