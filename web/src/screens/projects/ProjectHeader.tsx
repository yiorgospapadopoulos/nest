import { useState } from "react";
import type { RepoConfig } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { GENERAL, projectName } from "../../store/general.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { Sprite } from "../pixies/Sprite.tsx";
import { UsageChip } from "./UsageChip.tsx";

// The colour of a project's sprite without one of its own, as Settings > Project shows it.
const SPRITE_COLOR = "#8B7CF6";

interface Props {
  // The project shown, or General; the pixies show instead while `pixies` is set.
  repo: RepoConfig;
  pixies: boolean;
  onProject: (name: string) => void;
  onPixies: () => void;
  // The + on the right: New chat in the project, or New pixie.
  onAdd: () => void;
  // The usage beside it opens Settings > Usage (B116).
  onUsage: () => void;
}

/** A project's icon: General's own, its sprite when it has one, else its initials. */
export function RepoIcon({ repo }: { repo: RepoConfig }) {
  if (repo.name === GENERAL) return <Icon name="chat" className="gico" />;
  return repo.icon === null ? (
    <ProjectIcon name={repo.name} />
  ) : (
    <Sprite mascot={repo.icon} color={repo.icon_color ?? SPRITE_COLOR} size={22} />
  );
}

/**
 * The top of the Chats tab, as the Mac sidebar's (B102 item 19): the project's icon and
 * name opening a menu of Pixies and every project (the Mac's tabs), its current branch in
 * grey, the usage as the Mac's tab strip shows it, and a + for a new chat or pixie.
 */
export function ProjectHeader({ repo, pixies, onProject, onPixies, onAdd, onUsage }: Props) {
  const { state } = useStore();
  const [menu, setMenu] = useState(false);
  const close = () => {
    setMenu(false);
  };
  const name = pixies ? "Pixies" : projectName(repo.name);
  const branch = pixies ? null : repo.current_branch;

  return (
    <header className="bar">
      <h1 className="sr">Chats</h1>
      <button
        className="pmenu"
        aria-haspopup="menu"
        aria-label={`Project: ${name}`}
        onClick={() => {
          setMenu(true);
        }}
      >
        {pixies ? <Icon name="pixie" className="pmi" /> : <RepoIcon repo={repo} />}
        <span className="bar-t">{name}</span>
        <Icon name="chev" className="pcv" />
      </button>
      {branch !== null && (
        <span className="pbr">
          <Icon name="branch" />
          <span>{branch}</span>
        </span>
      )}
      <UsageChip onOpen={onUsage} />
      <button
        className="ib bar-add"
        aria-label={pixies ? "New pixie" : `New chat in ${name}`}
        onClick={onAdd}
      >
        <Icon name="plus" />
      </button>
      {menu && (
        <ActionSheet label="Projects" onClose={close}>
          <button
            className="asi"
            role="menuitemradio"
            aria-checked={pixies}
            onClick={() => {
              close();
              onPixies();
            }}
          >
            <Icon name="pixie" />
            <span>Pixies</span>
          </button>
          <button
            className="asi"
            role="menuitemradio"
            aria-checked={!pixies && repo.name === GENERAL}
            onClick={() => {
              close();
              onProject(GENERAL);
            }}
          >
            <Icon name="chat" />
            <span>General</span>
          </button>
          {state.repos.map((each) => (
            <button
              key={each.name}
              className="asi"
              role="menuitemradio"
              aria-checked={!pixies && each.name === repo.name}
              onClick={() => {
                close();
                onProject(each.name);
              }}
            >
              <RepoIcon repo={each} />
              <span>{each.name}</span>
            </button>
          ))}
        </ActionSheet>
      )}
    </header>
  );
}
