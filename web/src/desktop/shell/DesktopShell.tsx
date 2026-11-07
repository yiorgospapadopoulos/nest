import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../../store/context.ts";
import { draftKey } from "../../store/state.ts";
import { GENERAL, GENERAL_REPO, repoNamed } from "../../store/general.ts";
import { deviceStorage } from "../../store/legacyKeys.ts";
import { ArtifactsView } from "../artifacts/ArtifactsView.tsx";
import { useApi, useBridge } from "../context.ts";
import { ProjectState, type ProjectView } from "../layout/project.ts";
import { clampSidebar } from "../layout/sidebar.ts";
import { shortcutFor } from "../layout/shortcuts.ts";
import {
  closeProject,
  moveProject,
  openProject,
  orderAfterAdding,
  repoOrderAfterMove,
  selectPixies,
  selectProject,
  selectProjectAt,
  selectProjectOffset,
  withRepos,
} from "../layout/tabs.ts";
import { browserPane, terminalPane } from "../layout/tools.ts";
import { NoPixies } from "../pixies/NoPixies.tsx";
import { PixieDetailsPanel } from "../pixies/PixieDetailsPanel.tsx";
import { ShellSheets } from "../pixies/ShellSheets.tsx";
import { placeOf } from "../settings/catalog.ts";
import { SettingsPanel } from "../settings/SettingsPanel.tsx";
import { SetupGuide } from "../setup/SetupGuide.tsx";
import type { StepId } from "../setup/steps.ts";
import { closeTopOverlay } from "../ui/overlays.ts";
import type { Bridge } from "../bridge.ts";
import { Board } from "./Board.tsx";
import { ShellContext, type Shell } from "./context.ts";
import { loadDesk, saveDesk, type Desk } from "./desk.ts";
import { Palette } from "./Palette.tsx";
import type { NewChatChoice } from "../chat/placePicker.ts";
import { initTextLeft } from "./frame/gitInit.ts";
import { useGonePlaces } from "./frame/projectMap.ts";
import { draftPane } from "./panes.ts";
import { PixiesSidebar } from "./PixiesSidebar.tsx";
import { RightPanel } from "./RightPanel.tsx";
import { Sidebar } from "./Sidebar.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { TabStrip } from "./TabStrip.tsx";
import { terminals } from "./terminals.ts";
import { browserClosed, browsers } from "./toolSessions.ts";
import { useAppSwap } from "./useAppSwap.ts";
import { useWindowWatch } from "./useWindowWatch.ts";
import { WindowFrame } from "./WindowFrame.tsx";
import { Workspace } from "./Workspace.tsx";
import { routeLinkClick } from "../links.ts";

/** The desktop window, as the Mac's RootView: tab strip, sidebar, workspace, panel, status bar. */
export function DesktopShell() {
  const { state, actions } = useStore();
  const bridge = useBridge();
  const api = useApi();
  const storage = deviceStorage();
  const [saved, setDesk] = useState<Desk>(() => loadDesk(storage));
  const [settings, setSettings] = useState<Shell["settings"]>(null);
  const [guide, setGuide] = useState<Shell["guide"]>(null);
  const [guideStep, setGuideStep] = useState<StepId>("engine");
  const [palette, setPalette] = useState(false);
  // What the palette opens with typed in its search, as for /resume with a search.
  const [paletteSearch, setPaletteSearch] = useState("");
  const [sheet, setSheet] = useState<Shell["sheet"]>(null);
  const [pixieDetailsOpen, setPixieDetailsOpen] = useState(false);
  const [showsHiddenPixies, setShowsHiddenPixies] = useState(false);
  const size = useRef({ width: 900, height: 700 });
  const focusEvents = useRef(new Map<string, number>());
  const repoNames = useMemo(() => state.repos.map((r) => r.name), [state.repos]);
  // The tabs as the registered projects allow them: removed ones closed, the rest in order.
  const desk = useMemo(
    () => ({ ...saved, tabs: withRepos(saved.tabs, repoNames) }),
    [saved, repoNames],
  );

  useEffect(() => {
    saveDesk(storage, desk);
  }, [storage, desk]);

  // Until the daemon says whether this is a first run, the window cannot tell whether the
  // guide shows: it stays blank, so the projects never flash before the guide (B130). One
  // that does not answer counts as no first run.
  const [setupAsked, setSetupAsked] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .setup()
      .then(
        (setup) => {
          if (live && setup.first_run) setGuide("first");
        },
        () => undefined,
      )
      .finally(() => {
        if (live) setSetupAsked(true);
      });
    return () => {
      live = false;
    };
  }, [api]);

  // A project added here or elsewhere: the whole order is saved, so a restart keeps it.
  const knownRepos = useRef<string[] | null>(null);
  useEffect(() => {
    const before = knownRepos.current;
    knownRepos.current = repoNames;
    const order = before === null ? null : orderAfterAdding(before, repoNames);
    if (order !== null) api.reorderRepos(order).catch(() => undefined);
  }, [repoNames, api]);

  // A closed pane, or a project removed from the daemon, ends its shell (Shell.syncTools).
  useEffect(() => {
    const live = livePanes(desk, repoNames);
    terminals.keep(live);
    browsers.keep(live);
  }, [desk, repoNames]);

  const project = desk.tabs.current;
  const repo = (project === null ? undefined : repoNamed(state.repos, project)) ?? GENERAL_REPO;
  const current = useMemo(
    () => (project === null ? desk.pixies : (desk.projects[project] ?? new ProjectState())),
    [desk, project],
  );

  const shell = useMemo<Shell>(() => {
    const updateIn = (name: string | null, change: (s: ProjectState) => void) => {
      setDesk((d) => {
        const before = name === null ? d.pixies : (d.projects[name] ?? new ProjectState());
        const next = before.copy();
        change(next);
        return name === null
          ? { ...d, pixies: next }
          : { ...d, projects: { ...d.projects, [name]: next } };
      });
    };
    const update = (change: (s: ProjectState) => void) => {
      updateIn(project, change);
    };
    const openDraft = (place: NewChatChoice | null) => {
      // From the Pixies tab, in the project it came from, as the Mac's newChat.
      const name = project ?? desk.tabs.last ?? desk.tabs.open[0];
      if (name === undefined) return;
      // Settings sits over the chats, so it gives way for the draft.
      setSettings(null);
      setPalette(false);
      if (project === null) setTabs((tabs) => selectProject(tabs, name));
      const pane = draftPane();
      updateIn(name, (s) => {
        if (place !== null) s.draftPlaces.set(pane, place);
        s.openChat(pane, size.current);
      });
    };
    const setTabs = (change: (tabs: Desk["tabs"]) => Desk["tabs"]) => {
      setDesk((d) => ({ ...d, tabs: change(withRepos(d.tabs, repoNames)) }));
    };
    const openPane = (pane: string) => {
      update((s) => s.openChat(pane, size.current));
    };
    const toggle = (side: "leftCollapsed" | "rightCollapsed") => {
      update((s) => {
        s[side] = !s[side];
      });
    };
    return {
      desk,
      project,
      repo,
      state: current,
      update,
      workspaceSize: () => size.current,
      setWorkspaceSize: (next) => {
        size.current = next;
      },
      selectTab: (name) => {
        setSettings(null);
        setTabs((tabs) => (name === "pixies" ? selectPixies(tabs) : selectProject(tabs, name)));
      },
      openProject: (name) => {
        setSettings(null);
        setTabs((tabs) => openProject(tabs, name, repoNames));
      },
      closeTab: (name) => {
        setTabs((tabs) => closeProject(tabs, name));
      },
      moveTab: (name, index) => {
        const after = moveProject(desk.tabs, name, index);
        const order = repoOrderAfterMove(repoNames, desk.tabs, after, name);
        if (order === null) return;
        // Shown at once, as the daemon's own event will; saved for every device (D090).
        actions.receive({
          id: null,
          ts: new Date().toISOString(),
          session_id: null,
          type: "repos.reordered",
          payload: { order },
        });
        setTabs(() => after);
        api.reorderRepos(order).catch(() => {
          actions.toast("Could not save the project order", "error");
          void actions.resync();
        });
      },
      openIn: (app) => {
        if (project === null) return;
        api.openRepo(project, app).catch((error: unknown) => {
          actions.toast(
            error instanceof Error ? error.message : "Could not open the project",
            "error",
          );
        });
      },
      openPane,
      openChat: (id, event) => {
        if (event === undefined) focusEvents.current.delete(id);
        else focusEvents.current.set(id, event);
        const session = state.sessions[id];
        // A chat of another project opens in that project's tab, as the Mac reveals it.
        if (session !== undefined && session.repo !== project && session.pixie_id == null) {
          setTabs((tabs) => openProject(tabs, session.repo, repoNames));
          updateIn(session.repo, (s) => s.openChat(id, size.current));
          return;
        }
        openPane(id);
      },
      replacePane: (pane, next) => {
        update((s) => {
          s.replaceChat(pane, next);
        });
      },
      dropPane: (pane, target, side) => {
        update((s) => {
          s.dropChat(pane, target, side);
        });
      },
      closePane: (pane) => {
        if (project !== null) {
          const key = draftKey({ repo: project });
          if (initTextLeft(pane, current.layout.leaves, state.drafts[key]?.text ?? "")) {
            actions.setDraftText(key, "");
          }
        }
        update((s) => {
          s.closePane(pane);
        });
      },
      newChat: () => {
        openDraft(null);
      },
      newWorktreeFrom: (branch) => {
        openDraft({ kind: "newWorktree", from: branch });
      },
      newTerminal: () => {
        // One more terminal every time, as the Mac's New terminal; none in General, whose
        // folder belongs to Nest (B110).
        if (project === null || repo.path === "") return;
        update((s) => {
          s.openTool(terminalPane(repo.path), size.current);
        });
      },
      newBrowser: (url) => {
        if (url !== undefined) {
          void bridge.openBrowserWindow(url);
          return;
        }
        update((s) => {
          s.openTool(browserPane(), size.current);
        });
      },
      openPixie: (id) => {
        setSettings(null);
        setTabs(selectPixies);
        updateIn(null, (s) => s.openChat(id, size.current));
      },
      pixieDetailsOpen,
      togglePixieDetails: (id) => {
        const showing = pixieDetailsOpen && desk.pixies.layout.focused === id;
        updateIn(null, (s) => s.openChat(id, size.current));
        setPixieDetailsOpen(!showing);
      },
      showPixieDetails: (id) => {
        setSettings(null);
        setTabs(selectPixies);
        updateIn(null, (s) => s.openChat(id, size.current));
        setPixieDetailsOpen(true);
      },
      setPixieDetailsOpen,
      createPixie: (body, details) => {
        void actions.createPixie(body).then((created) => {
          if (created === null) return;
          setTabs(selectPixies);
          updateIn(null, (s) => s.openChat(created.id, size.current));
          setPixieDetailsOpen(details);
        });
      },
      showsHiddenPixies,
      setShowsHiddenPixies,
      showNeedsYou: (name) => {
        updateIn(name, (s) => {
          s.rightCollapsed = false;
          s.openCards.add("needsYou");
        });
      },
      openHabitRun: (session) => {
        setSheet({ habitRun: session });
      },
      openWork: (work) => {
        setSheet({ work });
      },
      sheet,
      closeSheet: () => {
        setSheet(null);
      },
      focusEvent: (pane) => focusEvents.current.get(pane),
      setView: (view: ProjectView) => {
        update((s) => {
          s.view = view;
        });
      },
      toggleSidebar: () => {
        toggle("leftCollapsed");
      },
      toggleActivity: () => {
        toggle("rightCollapsed");
      },
      setSidebarWidth: (width) => {
        setDesk((d) => ({ ...d, sidebarWidth: clampSidebar(width, window.innerWidth) }));
      },
      settings,
      openSettings: (target) => {
        setPalette(false);
        setSettings(placeOf(target));
      },
      closeSettings: () => {
        setSettings(null);
      },
      guide,
      openGuide: (step) => {
        setPalette(false);
        setGuideStep(step);
        setGuide("again");
      },
      closeGuide: () => {
        setGuide(null);
      },
      openGeneralChat: (model) => {
        setTabs((tabs) => openProject(tabs, GENERAL, repoNames));
        const pane = draftPane();
        updateIn(GENERAL, (s) => {
          if (model !== null) s.draftModels.set(pane, model);
          s.openChat(pane, size.current);
        });
      },
      palette,
      setPalette: (open) => {
        setPaletteSearch("");
        setPalette(open);
      },
      paletteSearch,
      searchPalette: (text) => {
        setPaletteSearch(text);
        setPalette(true);
      },
    };
  }, [
    desk,
    project,
    repo,
    current,
    repoNames,
    state.sessions,
    state.drafts,
    bridge,
    api,
    actions,
    settings,
    guide,
    palette,
    paletteSearch,
    sheet,
    pixieDetailsOpen,
    showsHiddenPixies,
  ]);

  useShortcuts(shell);
  usePlatformEvents(shell);
  useWindowWatch(shell);
  useGonePlaces();
  useAppSwap();

  if (!setupAsked) {
    return (
      <WindowFrame>
        <main className="center" aria-busy="true" aria-label="Loading" />
      </WindowFrame>
    );
  }

  if (guide !== null) {
    return (
      <ShellContext value={shell}>
        <WindowFrame>
          <SetupGuide firstRun={guide === "first"} start={guideStep} />
        </WindowFrame>
      </ShellContext>
    );
  }

  const pixies = project === null;
  const noPixies = pixies && Object.keys(state.pixies).length === 0;
  const focusedPixie =
    pixies && current.layout.focused !== null ? state.pixies[current.layout.focused] : undefined;
  return (
    <ShellContext value={shell}>
      <div className="dk-win">
        <TabStrip />
        <div className="dk-under">
          <div className="dk-body" inert={settings !== null}>
            {noPixies ? (
              <main className="dk-main" aria-label="Pixies">
                <NoPixies />
              </main>
            ) : (
              <>
                {pixies ? <PixiesSidebar /> : <Sidebar />}
                <main className="dk-main" aria-label={project ?? "Pixies"}>
                  {current.view === "artifacts" ? (
                    <ArtifactsView repo={project} />
                  ) : current.view === "board" && !pixies ? (
                    <Board />
                  ) : (
                    <Workspace />
                  )}
                </main>
                {!pixies && <RightPanel />}
                {pixieDetailsOpen && focusedPixie !== undefined && (
                  <PixieDetailsPanel pixie={focusedPixie} />
                )}
              </>
            )}
          </div>
          <StatusBar />
          {settings !== null && <SettingsPanel />}
        </div>
        <ShellSheets />
        {palette && <Palette />}
      </div>
    </ShellContext>
  );
}

/** The tool panes of the Pixies tab and of every registered project, open in a tab or not. */
function livePanes(desk: Desk, repos: string[]): Set<string> {
  const live = new Set(desk.pixies.tools.keys());
  for (const [name, state] of Object.entries(desk.projects)) {
    if (name !== GENERAL && !repos.includes(name)) continue;
    for (const id of state.tools.keys()) live.add(id);
  }
  return live;
}

/**
 * The tray menu's New chat and Settings, closed browser windows, and links: in the app
 * they open in the system's browser or mail app (links.ts) rather than replacing Nest's
 * page.
 */
function usePlatformEvents(shell: Shell) {
  const bridge = useBridge();
  const latest = useRef(shell);
  useEffect(() => {
    latest.current = shell;
  });
  useEffect(() => {
    const offs = [
      bridge.onTray("new-chat", () => {
        if (latest.current.guide === null) latest.current.newChat();
      }),
      bridge.onTray("open-settings", () => {
        if (latest.current.guide === null) latest.current.openSettings();
      }),
      bridge.onBrowserClosed((label) => {
        browserClosed(browsers, label);
      }),
    ];
    const onClick = (event: MouseEvent) => {
      routeLinkClick(event, bridge);
    };
    if (bridge.native) {
      document.addEventListener("click", onClick, true);
      document.addEventListener("auxclick", onClick, true);
    }
    return () => {
      for (const off of offs) off();
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("auxclick", onClick, true);
    };
  }, [bridge]);
}

/** The Mac's shortcuts with Ctrl (layout/shortcuts.ts), anywhere in the window. */
function useShortcuts(shell: Shell) {
  const bridge = useBridge();
  const latest = useRef(shell);
  useEffect(() => {
    latest.current = shell;
  });
  const tabs = useCallback((change: (t: Desk["tabs"]) => Desk["tabs"]) => {
    const next = change(latest.current.desk.tabs);
    if (next.current !== null) latest.current.selectTab(next.current);
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // The guide is the whole window: no shortcut acts behind it, and only one reopened
      // from Settings can be left this way.
      const { guide } = latest.current;
      if (guide !== null) {
        if (event.key === "Escape" && guide === "again" && !event.defaultPrevented) {
          latest.current.closeGuide();
        }
        return;
      }
      // Escape closes the topmost overlay wherever the focus is, as on the Mac. A sheet
      // over it handles its own Escape first and stops it.
      if (event.key === "Escape" && !event.defaultPrevented) {
        const s = latest.current;
        // A menu or popover is over everything else.
        if (closeTopOverlay()) {
          event.preventDefault();
          return;
        }
        if (s.palette) s.setPalette(false);
        else if (s.sheet !== null) s.closeSheet();
        else if (s.settings !== null) s.closeSettings();
        else if (s.state.view === "artifacts") s.setView("workspace");
        else return;
        event.preventDefault();
        return;
      }
      const found = shortcutFor(event);
      if (found === null) return;
      if (found.action === "sendMessage") {
        if (sendFocused()) event.preventDefault();
        return;
      }
      const s = latest.current;
      event.preventDefault();
      switch (found.action) {
        case "settings":
          s.openSettings();
          break;
        case "palette":
          s.setPalette(!s.palette);
          break;
        case "toggleSidebar":
          s.toggleSidebar();
          break;
        case "toggleActivity":
          s.toggleActivity();
          break;
        case "workspace":
          s.setView("workspace");
          break;
        case "board":
          s.setView("board");
          break;
        case "artifacts":
          s.setView("artifacts");
          break;
        case "newChat":
          s.newChat();
          break;
        case "closePane":
          closeFocused(s, bridge);
          break;
        case "newTerminal":
          s.newTerminal();
          break;
        case "newBrowser":
          s.newBrowser();
          break;
        case "previousProject":
          tabs((t) => selectProjectOffset(t, -1));
          break;
        case "nextProject":
          tabs((t) => selectProjectOffset(t, 1));
          break;
        case "project":
          tabs((t) => selectProjectAt(t, found.digit - 1));
          break;
        case "pixies":
          s.selectTab("pixies");
          break;
        case "openInVSCode":
          s.openIn("vscode");
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [bridge, tabs]);
}

/**
 * Send message (Ctrl+Enter), as the Mac's sendFocused: the composer being typed in, or with
 * nothing else focused, the focused pane's, gets Enter. Whether a composer took it.
 */
function sendFocused(): boolean {
  const composer = 'textarea[aria-label="Message"]';
  const active = document.activeElement;
  const field =
    active instanceof HTMLTextAreaElement && active.matches(composer)
      ? active
      : active === null || active === document.body
        ? document.querySelector<HTMLTextAreaElement>(`.dk-pane.focused ${composer}`)
        : null;
  if (field === null) return false;
  field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  return true;
}

/**
 * Ctrl+W, as the Mac's closeFocused: the topmost overlay first (a menu or popover, a sheet,
 * the palette, the work sheet, Settings, Artifacts), then the focused pane, then the window.
 */
function closeFocused(s: Shell, bridge: Bridge) {
  if (closeTopOverlay()) return;
  // The chat's own sheets close as their Escape closes them, the newest first.
  const sheet = [...document.querySelectorAll<HTMLElement>(".sheet[role=dialog], .asheet")].at(-1);
  if (sheet !== undefined) {
    sheet.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    return;
  }
  if (s.palette) s.setPalette(false);
  else if (s.sheet !== null) s.closeSheet();
  else if (s.settings !== null) s.closeSettings();
  else if (s.state.view === "artifacts") s.setView("workspace");
  else if (s.state.layout.focused !== null) s.closePane(s.state.layout.focused);
  else void bridge.close();
}
