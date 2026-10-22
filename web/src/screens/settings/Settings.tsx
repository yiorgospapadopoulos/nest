import { useEffect, type ReactNode } from "react";
import { SETTINGS_PAGES, type SettingsPage, type SettingsPageId } from "../../routes.ts";
import { useStore } from "../../store/context.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon, type IconName } from "../../ui/Icon.tsx";
import type { PixieTab } from "../pixies/PixieView.tsx";
import { AccountsPage } from "./AccountsPage.tsx";
import { AgentsPage } from "./AgentsPage.tsx";
import { AppearancePage } from "./AppearancePage.tsx";
import { ConfigurationView } from "./Configuration.tsx";
import { DevicesPage } from "./DevicesPage.tsx";
import { GeneralPage } from "./GeneralPage.tsx";
import { NotificationsPage } from "./NotificationsPage.tsx";
import { PixiesPage } from "./PixiesPage.tsx";
import { ProjectPage } from "./ProjectPage.tsx";
import { LinkRow, PageFrame } from "./rows.tsx";
import { StoragePage } from "./StoragePage.tsx";
import { UsageBreakdown } from "./UsageBreakdown.tsx";
import { UsagePage } from "./UsagePage.tsx";

const PAGES: Record<SettingsPageId, { title: string; icon: IconName }> = {
  general: { title: "General", icon: "gear" },
  appearance: { title: "Appearance", icon: "contrast" },
  notifications: { title: "Notifications", icon: "bell" },
  agents: { title: "Agents", icon: "bot" },
  usage: { title: "Usage", icon: "chart" },
  storage: { title: "Storage", icon: "drive" },
  pixies: { title: "Pixies", icon: "pixie" },
  accounts: { title: "Accounts", icon: "user" },
  devices: { title: "Devices", icon: "devices" },
  configuration: { title: "Configuration", icon: "list" },
};

interface Props {
  page: SettingsPage | null;
  onPage: (page: SettingsPage | null) => void;
  // Where a page's back button goes: the list, or the Projects tab it was opened from.
  back: string;
  onBack: () => void;
  onOpenPixie: (id: string, tab: PixieTab) => void;
}

/** The Settings tab (B81): the categories and the projects, each opening its page. */
export function Settings(props: Props) {
  // Settings' own look (B102 items 16, 17): flat rows like the Mac's, in settings.css.
  return (
    <div className="set">
      <SettingsBody {...props} />
    </div>
  );
}

function SettingsBody({ page, onPage, back, onBack, onOpenPixie }: Props) {
  const { state, actions } = useStore();

  useEffect(() => {
    void actions.loadAccount();
    void actions.loadChoices();
    void actions.loadSettings();
  }, [actions]);

  // A project removed, here or on the Mac, closes its page.
  const gone =
    page !== null && "project" in page && !state.repos.some((r) => r.name === page.project);
  useEffect(() => {
    if (gone) onBack();
  }, [gone, onBack]);

  if (page === null) {
    return (
      <>
        <div className="snav">
          <h1 className="snt">Settings</h1>
        </div>
        <ConnectedTo />
        <nav className="lgrp gl" aria-label="Settings">
          {SETTINGS_PAGES.map((id) => (
            <LinkRow
              key={id}
              icon={<Icon name={PAGES[id].icon} className="sico" />}
              label={PAGES[id].title}
              onOpen={() => {
                onPage({ page: id });
              }}
            />
          ))}
        </nav>
        {state.repos.length > 0 && (
          <section aria-labelledby="settings-projects">
            <h2 className="pg-h" id="settings-projects">
              Projects
            </h2>
            <div className="lgrp gl">
              {state.repos.map((repo) => (
                <LinkRow
                  key={repo.name}
                  icon={<ProjectIcon name={repo.name} />}
                  label={repo.name}
                  onOpen={() => {
                    onPage({ project: repo.name });
                  }}
                />
              ))}
            </div>
          </section>
        )}
      </>
    );
  }

  if ("detail" in page) {
    return (
      <UsageBreakdown
        onBack={() => {
          onPage({ page: "usage" });
        }}
      />
    );
  }

  if ("project" in page) {
    const repo = state.repos.find((r) => r.name === page.project);
    if (repo === undefined) return null;
    return (
      <PageFrame title={repo.name} back={back} onBack={onBack}>
        <ProjectPage key={repo.name} repo={repo} />
      </PageFrame>
    );
  }

  const body: Record<SettingsPageId, () => ReactNode> = {
    general: () => <GeneralPage />,
    appearance: () => <AppearancePage />,
    notifications: () => <NotificationsPage />,
    agents: () => <AgentsPage />,
    usage: () => (
      <UsagePage
        onDetails={() => {
          onPage({ detail: "usage" });
        }}
      />
    ),
    storage: () => <StoragePage />,
    pixies: () => <PixiesPage onOpenPixie={onOpenPixie} />,
    accounts: () => <AccountsPage />,
    devices: () => <DevicesPage />,
    configuration: () => <ConfigurationView />,
  };
  return (
    <PageFrame title={PAGES[page.page].title} back={back} onBack={onBack}>
      {body[page.page]()}
    </PageFrame>
  );
}

/** The daemon this app belongs to (B105): each machine's Nest is its own Home Screen app. */
function ConnectedTo() {
  const { state, address } = useStore();
  return (
    <section aria-labelledby="settings-connected">
      <h2 className="pg-h" id="settings-connected">
        Connected to
      </h2>
      <div className="lgrp gl">
        <div className="srow">
          <span className="cn">
            <span className="dot conn-dot" aria-hidden="true" />
            <span className="slab">
              {state.machine ?? "Your Mac"}
              <span className="hint mono">{address}</span>
            </span>
          </span>
        </div>
        <p className="srow note">
          This app is {state.machine ?? "your Mac"}&apos;s. For another machine, open its address in
          Safari and add it to the Home Screen: each one is its own app with its own pairing.
        </p>
      </div>
    </section>
  );
}
