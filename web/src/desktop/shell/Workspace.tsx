import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import {
  AgentPane,
  ChatPane,
  ClaudePane,
  DraftPane,
  WorkPane,
  type PaneChrome,
} from "../chat/ChatPane.tsx";
import { chatFit, FitContext } from "../chat/fit.ts";
import { Glyph } from "../chat/glyphs.tsx";
import { HeaderFrame, HeaderTitle } from "../chat/PaneHeader.tsx";
import { PortChips } from "../chat/RunControl.tsx";
import { runControl, runPanePlace, runPaneTitle } from "../chat/runState.ts";
import { StartView } from "../chat/StartView.tsx";
import { toolTitle, type ToolPane } from "../layout/tools.ts";
import {
  dropHit,
  grabArea,
  paneKind,
  type DropZone,
  type GutterFrame,
  type Rect,
  type Size,
} from "../layout/workspace.ts";
import { PANE_DRAG } from "./bits.tsx";
import { useShell, type Shell } from "./context.ts";
import { paneTarget } from "./panes.ts";
import { PixiePane } from "../pixies/PixiePane.tsx";
import { PixiesEmpty } from "./PixiesEmpty.tsx";
import { TerminalPane } from "./TerminalPane.tsx";
import { BrowserPane, RunPane } from "./ToolPanes.tsx";

// A pane dragged by its header swaps places rather than splitting.
const HEADER_DRAG = "application/x-nest-pane-header";

/**
 * The split workspace of up to four panes, edge to edge with a one pixel divider; every
 * pane but the focused one dims while two or more show (B93). Chats dropped from the
 * sidebar split a pane by where they land; dividers drag to resize.
 */
export function Workspace() {
  const shell = useShell();
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  const [hover, setHover] = useState<{ frame: Rect; zone: DropZone } | null>(null);
  const { layout } = shell.state;
  const pixies = shell.project === null;

  const { setWorkspaceSize } = shell;
  useLayoutEffect(() => {
    const element = box.current;
    if (element === null) return;
    const measure = () => {
      const next = { width: element.clientWidth, height: element.clientHeight };
      setSize(next);
      setWorkspaceSize(next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [setWorkspaceSize]);

  const dragged = (event: DragEvent) => {
    const types = event.dataTransfer.types;
    if (types.includes(HEADER_DRAG)) return "pane" as const;
    return types.includes(PANE_DRAG) ? ("chat" as const) : null;
  };
  const point = (event: DragEvent) => {
    const rect = box.current?.getBoundingClientRect();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  };
  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    const kind = dragged(event);
    if (kind === null) return;
    event.preventDefault();
    const { x, y } = point(event);
    // The dragged id is unreadable while dragging; the drop checks it again.
    const hit = dropHit(layout, x, y, size, "", kind);
    setHover(hit === null ? null : { frame: hit.frame, zone: hit.zone });
  };
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    const kind = dragged(event);
    setHover(null);
    if (kind === null) return;
    event.preventDefault();
    const pane = event.dataTransfer.getData(kind === "pane" ? HEADER_DRAG : PANE_DRAG);
    if (pane === "") return;
    if (layout.root === null) {
      shell.dropPane(pane, null, "left");
      return;
    }
    const { x, y } = point(event);
    const hit = dropHit(layout, x, y, size, pane, kind);
    if (hit === null) return;
    const { zone } = hit;
    if ("split" in zone) shell.dropPane(pane, hit.pane, zone.split);
    else if ("replace" in zone || "swap" in zone) {
      shell.update((s) => {
        s.layout.replace(hit.pane, pane);
        s.focusPane(pane);
      });
    }
  };

  const frames =
    layout.maximized === null
      ? layout.paneFrames(size)
      : [{ pane: layout.maximized, frame: { x: 0, y: 0, ...size } }];

  return (
    <div
      ref={box}
      className="dk-work"
      onDragOver={onDragOver}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setHover(null);
      }}
      onDrop={onDrop}
    >
      {layout.root === null && <EmptyWorkspace pixies={pixies} />}
      {size.width > 0 &&
        frames.map(({ pane, frame }) => <Pane key={pane} pane={pane} frame={frame} />)}
      {layout.maximized === null &&
        layout
          .gutterFrames(size)
          .map((gutter) => <Gutter key={gutter.split} gutter={gutter} size={size} />)}
      {hover !== null && !("none" in hover.zone) && (
        <div className="dk-drop" style={highlight(hover.frame, hover.zone)} />
      )}
    </div>
  );
}

function highlight(frame: Rect, zone: DropZone): CSSProperties {
  let rect = frame;
  if ("split" in zone) {
    const half = { width: frame.width / 2, height: frame.height / 2 };
    rect = {
      left: { ...frame, width: half.width },
      right: { ...frame, x: frame.x + half.width, width: half.width },
      top: { ...frame, height: half.height },
      bottom: { ...frame, y: frame.y + half.height, height: half.height },
    }[zone.split];
  }
  return { left: rect.x + 4, top: rect.y + 4, width: rect.width - 8, height: rect.height - 8 };
}

function EmptyWorkspace({ pixies }: { pixies: boolean }) {
  const shell = useShell();
  if (pixies) return <PixiesEmpty />;
  // The empty workspace's composer starts a chat that opens in a pane (StartSession.swift).
  return (
    <div className="dk-start">
      <StartView
        key={shell.repo.name}
        repo={shell.repo.name}
        onOpen={(id) => {
          shell.openChat(id);
        }}
        onCreated={(session) => {
          shell.openChat(session.id);
        }}
      />
    </div>
  );
}

/** A divider; dragging it resizes the split, kept above the panes' minimum sizes. */
function Gutter({ gutter, size }: { gutter: GutterFrame; size: Size }) {
  const shell = useShell();
  const area = grabArea(gutter);
  const row = gutter.direction === "row";
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    // No text selection starts, here or in a terminal next to it, while the divider moves.
    event.preventDefault();
    window.getSelection()?.removeAllRanges();
    document.documentElement.classList.add("dk-resizing");
    const start = row ? event.clientX : event.clientY;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    const move = (e: globalThis.PointerEvent) => {
      const moved = (row ? e.clientX : e.clientY) - start;
      shell.update((s) => {
        s.layout.resize(gutter.split, gutter.ratio + moved / gutter.span, size);
      });
    };
    const up = () => {
      document.documentElement.classList.remove("dk-resizing");
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      target.removeEventListener("lostpointercapture", up);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
    target.addEventListener("lostpointercapture", up);
  };
  return (
    <>
      <div
        className="dk-gutter"
        style={{
          left: gutter.frame.x,
          top: gutter.frame.y,
          width: gutter.frame.width,
          height: gutter.frame.height,
        }}
      />
      <div
        className={row ? "dk-grab row" : "dk-grab col"}
        role="separator"
        aria-orientation={row ? "vertical" : "horizontal"}
        aria-label="Resize panes"
        style={{ left: area.x, top: area.y, width: area.width, height: area.height }}
        onPointerDown={onPointerDown}
      />
    </>
  );
}

/** Actions that stay the same across renders, so effects in the chat view run once. */
function useStable(shell: Shell) {
  const latest = useRef(shell);
  useEffect(() => {
    latest.current = shell;
  });
  return useCallback(<A extends unknown[]>(act: (s: Shell, ...args: A) => void) => {
    return (...args: A) => {
      act(latest.current, ...args);
    };
  }, []);
}

function Pane({ pane, frame }: { pane: string; frame: Rect }) {
  const shell = useShell();
  const { layout } = shell.state;
  const kind = paneKind(pane);
  const dimmed = layout.isDimmed(pane);
  const focused = layout.focused === pane;
  const stable = useStable(shell);
  const [callbacks] = useState(() => ({
    close: stable((s) => {
      s.closePane(pane);
    }),
    maximize: stable((s) => {
      s.update((state) => {
        state.layout.toggleMaximize(pane);
      });
    }),
    // A draft's first message, or a Claude Code chat continued in Nest, keeps its pane.
    replace: stable((s, id: string) => {
      s.replacePane(pane, id);
    }),
  }));
  const maximized = layout.maximized === pane;
  const chrome: PaneChrome = {
    grip: (
      <span
        className="dc-grip"
        draggable
        title="Drag to swap"
        aria-hidden="true"
        onDragStart={(event) => {
          event.dataTransfer.setData(HEADER_DRAG, pane);
          event.dataTransfer.effectAllowed = "move";
        }}
      >
        <svg viewBox="0 0 8 12">
          {[2, 6, 10].flatMap((y) => [
            <circle key={`a${String(y)}`} cx="2" cy={y} r="1.1" />,
            <circle key={`b${String(y)}`} cx="6" cy={y} r="1.1" />,
          ])}
        </svg>
      </span>
    ),
    buttons: (
      <>
        <button
          className="dk-btn k-plain icon dc-pbtn"
          title={maximized ? "Restore" : "Maximize"}
          aria-label={maximized ? "Restore" : "Maximise"}
          onClick={callbacks.maximize}
        >
          <Glyph name={maximized ? "restore" : "maximize"} size={10} />
        </button>
        <button
          className="dk-btn k-plain icon dc-pbtn"
          title="Close"
          aria-label="Close pane"
          onClick={callbacks.close}
        >
          <Glyph name="close" size={10} />
        </button>
      </>
    ),
    onMaximize: callbacks.maximize,
    onClose: callbacks.close,
    dimmed,
  };

  let body: ReactNode;
  if (kind === "chat") {
    const target = paneTarget(pane, shell.repo.name, shell.project === null);
    if ("draft" in target) {
      body = (
        <DraftPane
          repo={target.draft}
          place={shell.state.draftPlaces.get(pane) ?? null}
          model={shell.state.draftModels.get(pane) ?? null}
          chrome={chrome}
          onCreated={(session) => {
            callbacks.replace(session.id);
          }}
        />
      );
    } else if ("claude" in target) {
      body = <ClaudePane id={target.claude} chrome={chrome} onContinued={callbacks.replace} />;
    } else if ("agentOf" in target) {
      body = <AgentPane session={target.agentOf} call={target.call} chrome={chrome} />;
    } else if ("workOf" in target) {
      body = <WorkPane session={target.workOf} who={target.who} chrome={chrome} />;
    } else if ("pixie" in target) {
      body = <PixiePane id={target.pixie} chrome={chrome} focused={focused} />;
    } else {
      body = <ChatPane id={target.id} chrome={chrome} focus={shell.focusEvent(pane) ?? null} />;
    }
  } else {
    const tool = shell.state.tools.get(pane);
    const title = tool === undefined ? "Pane" : toolTitle(tool);
    body = (
      <section className={dimmed ? "dc-pane dimmed dk-tool" : "dc-pane dk-tool"} aria-label={title}>
        <HeaderFrame
          grip={chrome.grip}
          buttons={chrome.buttons}
          onMaximize={chrome.onMaximize}
          label={title}
        >
          {tool !== undefined && kind === "run" ? (
            <RunHeader pane={tool} />
          ) : (
            <>
              <Icon name={kind === "browser" ? "devices" : "term"} className="dk-ticon" />
              <HeaderTitle title={title} />
              <span className="grow" />
            </>
          )}
        </HeaderFrame>
        <div className="dc-body">
          {tool !== undefined && kind === "terminal" && (
            <TerminalPane pane={tool} focused={focused} />
          )}
          {tool !== undefined && kind === "browser" && <BrowserPane pane={tool} />}
          {tool !== undefined && kind === "run" && <RunPane pane={tool} />}
        </div>
      </section>
    );
  }

  return (
    <div
      className={`dk-pane${dimmed ? " dim" : ""}${focused ? " focused" : ""}`}
      style={{ left: frame.x, top: frame.y, width: frame.width, height: frame.height }}
      onMouseDownCapture={() => {
        if (!focused) {
          shell.update((s) => {
            s.focusPane(pane);
          });
        }
      }}
    >
      <FitContext value={chatFit(frame.width)}>{body}</FitContext>
    </div>
  );
}

/** A run output pane's header: the command, where it runs, its ports, restart and stop (B108). */
function RunHeader({ pane }: { pane: ToolPane }) {
  const { state, actions } = useStore();
  const shell = useShell();
  const folder = pane.folder ?? "";
  const chat = pane.session ?? "";
  const status = state.runs[chat];
  const control = runControl(status, false, null);
  const place = runPanePlace(state.sessions[chat]);
  const alive = status?.state === "running" || status?.state === "starting";
  return (
    <>
      <HeaderTitle title={runPaneTitle(status)} />
      {place !== null && (
        <span className="dc-hmeta" title={folder}>
          {place}
        </span>
      )}
      <span className="grow" />
      {control?.kind === "running" && (
        <PortChips
          ports={control.ports}
          more={control.more}
          moreHelp={control.moreHelp}
          onOpen={(url) => {
            shell.newBrowser(url);
          }}
        />
      )}
      <button
        className="dk-btn k-plain icon"
        title="Restart"
        aria-label="Restart"
        disabled={status?.available !== true}
        onClick={() => void actions.runControl(chat, "restart")}
      >
        <Glyph name="refresh" size={10} />
      </button>
      <button
        className="dk-btn k-plain icon"
        title="Stop"
        aria-label="Stop"
        disabled={!alive}
        onClick={() => void actions.runControl(chat, "stop")}
      >
        <Glyph name="stop" size={8} />
      </button>
    </>
  );
}
