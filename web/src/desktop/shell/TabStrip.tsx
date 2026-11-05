import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type RefObject,
} from "react";
import type { RepoConfig } from "../../api/types.ts";
import { Sprite } from "../pixies/Sprite.tsx";
import { useStore } from "../../store/context.ts";
import { GENERAL, GENERAL_REPO, projectName, repoNamed } from "../../store/general.ts";
import { needsCount, needsTone, pixieList, unreadActions } from "../../store/selectors.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { useKeysText } from "../layout/useShortcuts.ts";
import type { StripGap } from "../layout/pillGap.ts";
import { stripFit, TAB_MAX, TAB_NARROW, TAB_SPACING, type StripFit } from "../layout/stripFit.ts";
import { reorderOffset, reorderTarget } from "../layout/tabs.ts";
import { ProjectMark } from "./bits.tsx";
import { AddProjectButton } from "./frame/AddProject.tsx";
import "./frame/frame.css";
import { UsageChip } from "./frame/UsageChip.tsx";
import { TAP_SLOP } from "./tap.ts";
import { useShell } from "./context.ts";
import { usePillGap } from "./usePillGap.ts";
import { WindowButtons } from "./WindowButtons.tsx";

const SPRITE_COLOR = "#8B7CF6";
// The strip's side paddings, the divider after the Pixies tab with its margins, and the
// space between the strip's parts (desktop.css .dk-tabs).
const PAD_LEFT = 10;
const PAD_RIGHT = 8;
const DIVIDER = 13;
const SPACE = 2;

/**
 * The window's title bar (frame A): the Pixies tab, the project tabs of one width with
 * their counts, a + for another project, the usage meter, search and the window buttons.
 */
export function TabStrip() {
  const { state } = useStore();
  const shell = useShell();
  // The tab being dragged, from where, and how far.
  const [dragging, setDragging] = useState<{ index: number; dx: number } | null>(null);
  const keysOf = useKeysText();
  const { open, current } = shell.desk.tabs;
  const gap = usePillGap();
  const strip = useRef<HTMLElement>(null);
  useHoverMarks(strip);
  // The tabs' width, and whether the strip keeps clear of the pill (layout/stripFit.ts).
  const fit = useStripFit(strip, gap, open.length);
  // A project tab's width plus the space between tabs: one step of a drag (TabReorder.swift).
  const step = fit.tabWidth + TAB_SPACING;
  const landing =
    dragging === null ? null : reorderTarget(dragging.index, dragging.dx, step, open.length);
  const list = useRef<HTMLDivElement>(null);
  // General stays first while open and never drags, so it stays put when the others scroll.
  const general = open[0] === GENERAL;
  const tab = (name: string, index: number) => {
    const on = current === name;
    const width = on ? fit.currentWidth : fit.tabWidth;
    return (
      <ProjectTab
        key={name}
        name={name}
        index={index}
        repo={repoNamed(state.repos, name) ?? (name === GENERAL ? GENERAL_REPO : undefined)}
        current={on}
        width={width}
        narrow={width < TAB_NARROW}
        step={step}
        offset={
          dragging === null || landing === null
            ? 0
            : dragging.index === index
              ? dragging.dx
              : reorderOffset(index, dragging.index, landing, step)
        }
        onDrag={(dx) => {
          setDragging(dx === null ? null : { index, dx });
        }}
      />
    );
  };
  // Scrolling tabs keep the chosen one in view, and fade at an edge with more beyond it.
  useEffect(() => {
    edges(list.current);
    if (!fit.overflows) return;
    list.current
      ?.querySelector(".dk-proj.on")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [fit.overflows, current]);

  return (
    <header ref={strip} className="dk-tabs" data-tauri-drag-region>
      <div
        className="dk-tleft"
        style={
          gap !== null && fit.keepsGap ? { maxWidth: Math.max(0, gap.left - PAD_LEFT) } : undefined
        }
      >
        <div className="dk-tabset" role="tablist" aria-label="Projects">
          <PixiesTab />
          <span className="dk-sep" aria-hidden="true" />
          {general && tab(GENERAL, 0)}
          <div
            ref={list}
            className={fit.overflows ? "dk-tablist scrolls" : "dk-tablist"}
            onScroll={(event) => {
              edges(event.currentTarget);
            }}
            onWheel={(event) => {
              // A mouse wheel turns the scrolling tabs sideways.
              if (!fit.overflows || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
              event.currentTarget.scrollLeft += event.deltaY;
            }}
          >
            {open.map((name, index) => (general && index === 0 ? null : tab(name, index)))}
          </div>
        </div>
        <AddProjectButton />
      </div>
      <span className="grow" data-tauri-drag-region />
      <div className="dk-tright">
        <UsageChip />
        <button
          className="dk-search"
          onClick={() => {
            shell.setPalette(true);
          }}
        >
          <Icon name="search" />
          <span>Search</span>
          <kbd>{keysOf("palette")}</kbd>
        </button>
        <WindowButtons />
      </div>
    </header>
  );
}

/** Marks which ends of the scrolling tabs have more beyond them, for their fade. */
function edges(list: HTMLElement | null) {
  if (list === null) return;
  const scrolls = list.scrollWidth > list.clientWidth + 1;
  list.toggleAttribute("data-more-left", scrolls && list.scrollLeft > 1);
  list.toggleAttribute(
    "data-more-right",
    scrolls && list.scrollLeft + list.clientWidth < list.scrollWidth - 1,
  );
}

/**
 * The strip's fit for its width, the pill's gap and the open tabs, from the sizes of what
 * keeps its size: the Pixies tab and the + on the left, usage, search and the window
 * buttons on the right. Measured again whenever any of them changes size.
 */
function useStripFit(
  strip: RefObject<HTMLElement | null>,
  gap: StripGap | null,
  tabs: number,
): StripFit {
  const [sizes, setSizes] = useState({ width: 0, lead: 0, trail: 0 });
  useEffect(() => {
    const header = strip.current;
    if (header === null) return;
    const parts = () => ({
      pixies: header.querySelector<HTMLElement>(".dk-tabset > .dk-tab:first-child"),
      add: header.querySelector<HTMLElement>(".dk-tleft > .dk-tadd"),
      right: header.querySelector<HTMLElement>(".dk-tright"),
    });
    const measure = () => {
      const { pixies, add, right } = parts();
      const lead =
        PAD_LEFT +
        (pixies?.offsetWidth ?? 0) +
        SPACE +
        DIVIDER +
        SPACE +
        SPACE +
        (add?.offsetWidth ?? 0);
      // The right cluster, the space either side of the spacer and the strip's padding.
      const trail = (right?.offsetWidth ?? 0) + 2 * SPACE + PAD_RIGHT;
      const next = { width: header.clientWidth, lead, trail };
      setSizes((now) =>
        now.width === next.width && now.lead === next.lead && now.trail === next.trail ? now : next,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    for (const part of Object.values(parts())) if (part !== null) observer.observe(part);
    return () => {
      observer.disconnect();
    };
  }, [strip]);
  // Before the first measure the tabs keep their full width.
  if (sizes.width === 0) {
    return { tabWidth: TAB_MAX, currentWidth: TAB_MAX, keepsGap: gap !== null, overflows: false };
  }
  return stripFit({ ...sizes, gap, tabs });
}

/**
 * Marks the tab under the pointer with data-hover, worked out from every pointer move and
 * cleared when the pointer leaves the window or it loses focus. WebKitGTK keeps :hover on
 * a tab the pointer left when tabs moved under a still pointer or the pointer left the
 * window fast; the strip's CSS (frame.css) shows a tab's hover only while it is marked.
 */
function useHoverMarks(strip: RefObject<HTMLElement | null>) {
  useEffect(() => {
    let marked: Element | null = null;
    const mark = (tab: Element | null) => {
      if (tab === marked) return;
      marked?.removeAttribute("data-hover");
      tab?.setAttribute("data-hover", "");
      marked = tab;
    };
    const onMove = (event: globalThis.PointerEvent) => {
      const target = event.target;
      const tab = target instanceof Element ? target.closest(".dk-tab") : null;
      mark(tab !== null && strip.current?.contains(tab) === true ? tab : null);
    };
    const onOut = (event: globalThis.PointerEvent) => {
      if (event.relatedTarget === null) mark(null);
    };
    const clear = () => {
      mark(null);
    };
    window.addEventListener("pointermove", onMove, { capture: true, passive: true });
    document.addEventListener("pointerout", onOut, true);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("pointermove", onMove, true);
      document.removeEventListener("pointerout", onOut, true);
      window.removeEventListener("blur", clear);
      mark(null);
    };
  }, [strip]);
}

function PixiesTab() {
  const { state } = useStore();
  const shell = useShell();
  const keysOf = useKeysText();
  const current = shell.project === null;
  const pixies = pixieList(state);
  const first = pixies[0];
  const attention =
    Object.values(state.approvals).filter((a) => a.repo.startsWith("pixie:")).length +
    unreadActions(state);
  const running = pixies.some((p) => {
    const chat = Object.values(state.sessions).find(
      (s) => s.pixie_id === p.id && s.habit_run_id == null,
    );
    return chat?.state === "running" || chat?.state === "starting";
  });
  return (
    <button
      role="tab"
      aria-selected={current}
      className={current ? "dk-tab dk-ptab on" : "dk-tab dk-ptab"}
      aria-label={attention > 0 ? `Pixies, ${String(attention)} need you` : "Pixies"}
      title={`Pixies (${keysOf("pixies")})`}
      onClick={() => {
        shell.selectTab("pixies");
      }}
    >
      <Sprite
        mascot={first?.mascot ?? "bluebell"}
        color={first?.color ?? SPRITE_COLOR}
        size={15}
        working={running}
      />
      <span className="dk-tname">Pixies</span>
      <TabStatus tone={attention > 0 ? "wait" : null} running={running} />
    </button>
  );
}

interface TabProps {
  name: string;
  index: number;
  repo: RepoConfig | undefined;
  current: boolean;
  // The tab's width, and one step of a drag: a tab's width and the space between tabs.
  width: number;
  // Its parts sit closer, so its count still shows.
  narrow: boolean;
  step: number;
  // How far it is moved now: following the pointer, or sliding aside for a dragged tab.
  offset: number;
  onDrag: (dx: number | null) => void;
}

/** A project tab, dragged along the strip to reorder it (TabReorder.swift). */
function ProjectTab({ name, index, repo, current, width, narrow, step, offset, onDrag }: TabProps) {
  const { state } = useStore();
  const shell = useShell();
  const attention = needsCount(state, name);
  const tone = needsTone(state, name);
  const running = Object.values(state.sessions).some(
    (s) => s.repo === name && (s.state === "running" || s.state === "starting"),
  );
  const count = shell.desk.tabs.open.length;
  const canClose = count > 1;

  /**
   * A press selects the tab on its release, or drags it along the strip once it moves
   * further than a tap (General stays first, so it never drags). The move and the release
   * are followed on the window, without pointer capture: captured on the press, WebKitGTK
   * sent no click for a zero-length press (an xdotool click, a quick touchpad tap).
   */
  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const x = event.clientX;
    const y = event.clientY;
    let dx = 0;
    let moved = false;
    const move = (next: globalThis.PointerEvent) => {
      dx = next.clientX - x;
      if (!moved && name !== GENERAL && Math.abs(dx) > TAP_SLOP) moved = true;
      if (moved) onDrag(dx);
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
    };
    const up = (last: globalThis.PointerEvent) => {
      end();
      if (moved) {
        shell.moveTab(name, reorderTarget(index, dx, step, count));
        onDrag(null);
      } else if (Math.hypot(last.clientX - x, last.clientY - y) <= TAP_SLOP) {
        shell.selectTab(name);
      }
    };
    const cancel = () => {
      end();
      if (moved) onDrag(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  };
  // Enter or Space: a click with no pointer behind it.
  const onClick = (event: MouseEvent<HTMLElement>) => {
    if (event.detail === 0) shell.selectTab(name);
  };

  return (
    <div
      className={["dk-tab dk-ptab dk-proj", current ? "on" : "", narrow ? "narrow" : ""]
        .filter(Boolean)
        .join(" ")}
      style={
        offset === 0
          ? { width }
          : { width, transform: `translateX(${String(offset)}px)`, zIndex: 2 }
      }
    >
      <button
        role="tab"
        aria-selected={current}
        className="dk-tabb"
        aria-label={
          attention > 0 ? `${projectName(name)}, ${String(attention)} need you` : projectName(name)
        }
        onPointerDown={onPointerDown}
        onClick={onClick}
      >
        <ProjectMark name={name} repo={repo} size={13} />
        <span className="dk-tname">{projectName(name)}</span>
        <TabStatus tone={tone} running={running} />
      </button>
      {canClose && (
        <button
          className={current ? "dk-tclose" : "dk-tclose hover"}
          aria-label={`Close ${projectName(name)}`}
          onClick={() => {
            shell.closeTab(name);
          }}
        >
          <Icon name="x" />
        </button>
      )}
    </div>
  );
}

/** The fireflies while a chat runs, else a dot in the colour of what needs the user. */
function TabStatus({ tone, running }: { tone: "rev" | "wait" | null; running: boolean }) {
  if (running) return <Fireflies size={9} />;
  return tone === null ? null : <span className={`dot s-${tone}`} aria-hidden="true" />;
}
