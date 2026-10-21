import { useState } from "react";
import type { RepoConfig } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { ProjectIcon } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { Sprite } from "../pixies/Sprite.tsx";

// The colour of a project's sprite without one of its own, as Settings > Project shows it.
const SPRITE_COLOR = "#8B7CF6";

interface Props {
  // The project shown, or null for the pixies (or no project at all).
  repo: RepoConfig | null;
  pixies: boolean;
  onProject: (name: string) => void;
  onPixies: () => void;
  // The + on the right: New chat in the project, or New pixie.
  onAdd: (() => void) | null;
  onSettings: (name: string) => void;
}

/** A project's icon: its sprite when it has one, else its initials. */
export function RepoIcon({ repo }: { repo: RepoConfig }) {
  return repo.icon === null ? (
    <ProjectIcon name={repo.name} />
  ) : (
    <Sprite mascot={repo.icon} color={repo.icon_color ?? SPRITE_COLOR} size={22} />
  );
}

/**
 * The top of the Chats tab, as the Mac sidebar's (B102 item 19): the project's icon and
 * name opening a menu of Pixies and every project (the Mac's tabs), its current branch in
 * grey, and a + for a new chat or pixie.
 */
export function ProjectHeader({ repo, pixies, onProject, onPixies, onAdd, onSettings }: Props) {
  const { state } = useStore();
  const [menu, setMenu] = useState(false);
  const close = () => {
    setMenu(false);
  };
  const name = pixies ? "Pixies" : (repo?.name ?? "none");
  const branch = pixies ? null : (repo?.current_branch ?? null);

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
        {pixies ? <Icon name="pixie" className="pmi" /> : repo !== null && <RepoIcon repo={repo} />}
        <span className="bar-t">{pixies || repo !== null ? name : "No project"}</span>
        <Icon name="chev" className="pcv" />
      </button>
      {branch !== null && (
        <span className="pbr">
          <Icon name="branch" />
          <span>{branch}</span>
        </span>
      )}
      {onAdd !== null && (
        <button
          className="ib bar-add"
          aria-label={pixies ? "New pixie" : `New chat in ${name}`}
          onClick={onAdd}
        >
          <Icon name="plus" />
        </button>
      )}
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
          {state.repos.map((each) => (
            <button
              key={each.name}
              className="asi"
              role="menuitemradio"
              aria-checked={!pixies && each.name === repo?.name}
              onClick={() => {
                close();
                onProject(each.name);
              }}
            >
              <RepoIcon repo={each} />
              <span>{each.name}</span>
            </button>
          ))}
          {!pixies && repo !== null && (
            <button
              className="asi"
              role="menuitem"
              onClick={() => {
                close();
                onSettings(repo.name);
              }}
            >
              <Icon name="gear" />
              <span>Settings for {repo.name}</span>
            </button>
          )}
        </ActionSheet>
      )}
    </header>
  );
}
