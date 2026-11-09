import type { RepoConfig } from "../../api/types.ts";
import { Sprite } from "../pixies/Sprite.tsx";
import { GENERAL } from "../../store/general.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";

/** The classic git branch, as the chat's `branch` glyph. */
export function BranchIcon() {
  return (
    <svg className="dk-branch" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="4.5" cy="3.5" r="1.75" />
      <circle cx="4.5" cy="12.5" r="1.75" />
      <circle cx="11.5" cy="3.5" r="1.75" />
      <path d="M4.5 5.25v5.5M11.5 5.25v1a2.25 2.25 0 0 1-2.25 2.25h-2.5A2.25 2.25 0 0 0 4.5 10.75" />
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
