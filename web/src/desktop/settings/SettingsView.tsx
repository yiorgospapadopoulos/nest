import { useEffect, useMemo, useState, type ReactNode } from "react";
import { newCount } from "../../screens/settings/featureNew.ts";
import { useStore } from "../../store/context.ts";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import { ProjectMark } from "../shell/bits.tsx";
import { useShell } from "../shell/context.ts";
import { Button } from "../ui/controls.tsx";
import { listed, placeTitle, samePlace, type FixedPage, type SettingsPlace } from "./catalog.ts";
import { SettingsVisitContext, type SettingsVisit } from "./context.ts";
import { AccountsPage } from "./pages/AccountsPage.tsx";
import { AddProjectPage } from "./pages/AddProjectPage.tsx";
import { AgentsPage } from "./pages/AgentsPage.tsx";
import { AppearancePage } from "./pages/AppearancePage.tsx";
import { ConfigurationPage } from "./pages/ConfigurationPage.tsx";
import { DevicesPage } from "./pages/DevicesPage.tsx";
import { FeaturesPage } from "./pages/FeaturesPage.tsx";
import { GeneralPage } from "./pages/GeneralPage.tsx";
import { NotificationsPage } from "./pages/NotificationsPage.tsx";
import { PerformancePage } from "./pages/PerformancePage.tsx";
import { PixiesPage } from "./pages/PixiesPage.tsx";
import { ProjectPage } from "./pages/ProjectPage.tsx";
import { ShortcutsPage } from "./pages/ShortcutsPage.tsx";
import { StoragePage } from "./pages/StoragePage.tsx";
import { UsagePage } from "./pages/UsagePage.tsx";
import "./settings.css";

const ICONS: Record<FixedPage | "addProject", IconName> = {
  general: "gear",
  appearance: "contrast",
  notifications: "bell",
  agents: "bot",
  usage: "chart",
  performance: "gauge",
  storage: "drive",
  pixies: "pixie",
  accounts: "user",
  devices: "devices",
  shortcuts: "lines",
  configuration: "list",
  features: "book",
  addProject: "plus",
};

const PAGES: Record<FixedPage | "addProject", () => ReactNode> = {
  general: () => <GeneralPage />,
  appearance: () => <AppearancePage />,
  notifications: () => <NotificationsPage />,
  agents: () => <AgentsPage />,
  usage: () => <UsagePage />,
  performance: () => <PerformancePage />,
  storage: () => <StoragePage />,
  pixies: () => <PixiesPage />,
  accounts: () => <AccountsPage />,
  devices: () => <DevicesPage />,
  shortcuts: () => <ShortcutsPage />,
  configuration: () => <ConfigurationPage />,
  features: () => <FeaturesPage />,
  addProject: () => <AddProjectPage />,
};

/** A page's icon: a project's own, else its glyph. */
function PlaceIcon({ place }: { place: SettingsPlace }) {
  const { state } = useStore();
  if ("project" in place) {
    return (
      <ProjectMark name={place.project} repo={state.repos.find((r) => r.name === place.project)} />
    );
  }
  return <Icon name={ICONS[place.page]} />;
}

/**
 * Settings in the window, in place of the tab's content, as the Mac's Settings window
 * (SettingsWindow.swift): a sidebar with the search field, the pages, the projects and Add
 * project, and whether the Nest service answers; beside it the page's header and its body.
 */
export function SettingsView() {
  const { state, actions } = useStore();
  const shell = useShell();
  const [query, setQuery] = useState("");
  const [visitNew, setVisitNew] = useState<string[] | null>(null);
  const visit = useMemo<SettingsVisit>(() => ({ visitNew, setVisitNew }), [visitNew]);
  const asked = shell.settings ?? { page: "general" };
  // A removed project's page falls back to General.
  const place: SettingsPlace =
    "project" in asked && !state.repos.some((r) => r.name === asked.project)
      ? { page: "general" }
      : asked;

  useEffect(() => {
    void actions.loadAccount();
    void actions.loadChoices();
    void actions.loadSettings();
  }, [actions]);

  const catalog = state.settings.features;
  const featureLabels = useMemo(
    () => catalog?.groups.flatMap((g) => [g.name, ...g.features.map((f) => f.name)]) ?? [],
    [catalog],
  );
  const projects = state.repos.map((r) => r.name);
  const shown = listed(projects, query, featureLabels);
  const open = (entry: SettingsPlace) => {
    shell.openSettings("project" in entry ? { project: entry.project } : entry);
  };
  const fresh = catalog === null ? 0 : newCount(catalog, visitNew);
  const repo = "project" in place ? state.repos.find((r) => r.name === place.project) : undefined;

  const item = (entry: SettingsPlace) => {
    const on = samePlace(entry, place);
    const key = "project" in entry ? `project:${entry.project}` : entry.page;
    return (
      <button
        key={key}
        className={on ? "dks-item on" : "dks-item"}
        aria-current={on ? "page" : undefined}
        onClick={() => {
          open(entry);
        }}
      >
        <PlaceIcon place={entry} />
        <span className="dks-itemt">{placeTitle(entry)}</span>
        {"page" in entry && entry.page === "features" && fresh > 0 && (
          <span className="dks-new" aria-label={`${String(fresh)} new`}>
            {fresh}
            <i />
          </span>
        )}
      </button>
    );
  };

  return (
    <SettingsVisitContext value={visit}>
      <div className="dks" role="region" aria-label="Settings">
        <nav className="dks-side" aria-label="Settings pages">
          <label className="dks-search">
            <Icon name="search" />
            <input
              placeholder="Search settings"
              aria-label="Search settings"
              value={query}
              spellCheck={false}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
            />
          </label>
          <div className="dks-list">
            {shown.pages.map(item)}
            {shown.projects.length > 0 && <h2 className="dks-group">Projects</h2>}
            {shown.projects.map(item)}
            {shown.pages.length === 0 && shown.projects.length === 0 && (
              <p className="dks-group">No matches</p>
            )}
          </div>
          <div className="dks-foot">
            <i className={state.reconnecting ? "wait" : "ok"} />
            {state.reconnecting ? "Nest service not connected" : "Nest service running"}
          </div>
        </nav>
        <section className="dks-detail" aria-label={placeTitle(place)}>
          <header className="dks-head">
            <PlaceIcon place={place} />
            <div className="dks-headt">
              <h1>{placeTitle(place)}</h1>
              {repo !== undefined && <span className="dks-path">{repo.path}</span>}
            </div>
            <Button kind="plain" iconOnly aria-label="Close settings" onClick={shell.closeSettings}>
              <Icon name="x" />
            </Button>
          </header>
          <div
            className="dks-body"
            key={"project" in place ? `project:${place.project}` : place.page}
          >
            <div className="dks-page">
              {"project" in place
                ? repo !== undefined && <ProjectPage key={repo.name} repo={repo} />
                : PAGES[place.page]()}
            </div>
          </div>
        </section>
      </div>
    </SettingsVisitContext>
  );
}
