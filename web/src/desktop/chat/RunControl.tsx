// The Run control at the right of a chat's header (B108), as the Mac's RunControlView:
// Run opens the run's output pane beside the chat, keeping the focus in the chat, and
// starts the folder's run command; then Starting, the port chips and stop, or Exited N.
import { useEffect } from "react";
import type { RunStatus } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { useShell } from "../shell/context.ts";
import { useFit } from "./fit.ts";
import { Glyph } from "./glyphs.tsx";
import { runControl, type RunPort } from "./runState.ts";

/** Opens the folder's output pane: an open one stays as it is, else a new one beside the chat. */
function useRunOutput(chat: string): (status: RunStatus) => void {
  const shell = useShell();
  return (status) => {
    if (status.folder === null) return;
    const folder = status.folder;
    shell.update((s) => {
      s.runOutput(folder, chat, chat, shell.workspaceSize());
    });
  };
}

/**
 * Reads the chat's run again when its folder changes, as once its worktree exists (the
 * Mac's PaneView task), and when its project's settings change (`repo.updated`), so Run
 * shows or goes as the project's run command is added or removed.
 */
function useFreshRun(chat: string) {
  const { state, actions } = useStore();
  const session = state.sessions[chat];
  const folder = session?.worktree_path ?? session?.cwd ?? null;
  const repo = session?.repo ?? null;
  useEffect(() => {
    void actions.loadRun(chat);
  }, [actions, chat, folder]);
  useEffect(
    () =>
      actions.onEvent((event) => {
        if (event.type === "repo.updated" && event.payload.name === repo) {
          void actions.loadRun(chat);
        }
      }),
    [actions, chat, repo],
  );
}

export function RunControlView({ chat }: { chat: string }) {
  const { state, actions } = useStore();
  const shell = useShell();
  const fit = useFit();
  const openOutput = useRunOutput(chat);
  useFreshRun(chat);
  const status = state.runs[chat];
  const control = runControl(status, !fit.showsAllPorts, null);
  if (control === null || status === undefined) return null;
  const start = () => {
    openOutput(status);
    void actions.runControl(chat, "start");
  };
  switch (control.kind) {
    case "run":
      return (
        <button className="dc-run" title={control.help} onClick={start}>
          <Glyph name="play" size={8} />
          Run
        </button>
      );
    case "exited":
      return (
        <button className="dc-run bad" title={control.help} onClick={start}>
          <Glyph name="play" size={8} />
          {control.label}
        </button>
      );
    case "starting":
      return (
        <button
          className="dc-run"
          title={control.help}
          onClick={() => void actions.runControl(chat, "stop")}
        >
          <span className="dc-spin" aria-hidden="true" />
          Starting
        </button>
      );
    case "running":
      return (
        <span className="dc-runports">
          <PortChips
            ports={control.ports}
            more={control.more}
            moreHelp={control.moreHelp}
            onOpen={(url) => {
              shell.newBrowser(url);
            }}
          />
          <button
            className="dk-btn k-plain icon dc-runstop"
            title={control.stopHelp}
            aria-label="Stop"
            onClick={() => void actions.runControl(chat, "stop")}
          >
            <Glyph name="stop" size={8} />
          </button>
        </span>
      );
  }
}

/** The run's ports, the first with its green dot, and "+N" for the rest. */
export function PortChips({
  ports,
  more,
  moreHelp,
  onOpen,
}: {
  ports: RunPort[];
  more: number;
  moreHelp: string | null;
  onOpen: (url: string) => void;
}) {
  return (
    <>
      {ports.map((port) => (
        <button
          key={port.port}
          className="dc-port"
          title={port.help}
          aria-label={`Port ${String(port.port)}`}
          disabled={port.url === null}
          onClick={() => {
            if (port.url !== null) onOpen(port.url);
          }}
        >
          {port.live && <span className="dc-live-dot" aria-hidden="true" />}
          {port.port}
        </button>
      ))}
      {more > 0 && (
        <span className="dc-portmore" title={moreHelp ?? undefined}>
          +{more}
        </span>
      )}
    </>
  );
}
