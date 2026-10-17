import type { KeyboardEvent } from "react";
import type { Tab } from "../routes.ts";
import { Icon, type IconName } from "../ui/Icon.tsx";

// Arrow keys move between tabs, wrapping around.
const NEXT: Record<Tab, Tab> = { inbox: "projects", projects: "settings", settings: "inbox" };
const PREVIOUS: Record<Tab, Tab> = { inbox: "settings", projects: "inbox", settings: "projects" };

const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: "inbox", label: "Inbox", icon: "inbox" },
  { id: "projects", label: "Projects", icon: "folder" },
  { id: "settings", label: "Settings", icon: "gear" },
];

export function TabBar({
  tab,
  onTab,
  badge,
}: {
  tab: Tab;
  onTab: (tab: Tab) => void;
  badge: number;
}) {
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const next =
      event.key === "ArrowRight" ? NEXT[tab] : event.key === "ArrowLeft" ? PREVIOUS[tab] : null;
    if (next === null) return;
    event.preventDefault();
    onTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  };

  return (
    <nav className="tabbar gl" role="tablist" aria-label="Sections" onKeyDown={onKeyDown}>
      {TABS.map((t) => (
        <button
          key={t.id}
          id={`tab-${t.id}`}
          className="tb"
          role="tab"
          aria-selected={tab === t.id}
          aria-controls={`view-${t.id}`}
          tabIndex={tab === t.id ? 0 : -1}
          onClick={() => {
            onTab(t.id);
          }}
        >
          <Icon name={t.icon} />
          <span>{t.label}</span>
          {t.id === "inbox" && badge > 0 && (
            <span className="badge" aria-label={`${String(badge)} need you`}>
              {badge}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}
