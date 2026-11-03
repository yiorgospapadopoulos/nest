import type { RepoConfig } from "../../api/types.ts";
import { Sprite } from "../pixies/Sprite.tsx";
import { GENERAL } from "../../store/general.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

/** The Mac's branch mark: two lines joining into one, as SF Symbols' fork. */
export function ForkIcon() {
  return (
    <svg className="dk-fork" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M3 1.5v2.2c0 1.6 1.3 2.3 3 3.1M9 1.5v2.2c0 1.6-1.3 2.3-3 3.1M6 6.8v3.7" />
    </svg>
  );
}

const SPRITE_COLOR = "#8B7CF6";

/** A project's icon at the tab and sidebar size: General's, its sprite, or initials. */
export function ProjectMark({
  name,
  repo,
  size = 16,
}: {
  name: string;
  repo: RepoConfig | undefined;
  size?: number;
}) {
  if (name === GENERAL) return <Icon name="chat" className="dk-pmark" />;
  if (repo?.icon != null) {
    return <Sprite mascot={repo.icon} color={repo.icon_color ?? SPRITE_COLOR} size={size} />;
  }
  return <ProjectIcon name={name} />;
}

// What a sidebar row carries when dragged onto the workspace.
export const PANE_DRAG = "application/x-nest-pane";
