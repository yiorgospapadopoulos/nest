import type { RepoConfig } from "../api/types.ts";

// General's chats have no project (B110): the daemon runs them in a folder it owns and never
// lists it with the projects, so the PWA knows it by its reserved name.
export const GENERAL = "general";

export const GENERAL_REPO: RepoConfig = {
  name: GENERAL,
  path: "",
  git: false,
  default_branch: null,
  current_branch: null,
  selected_place: null,
  selected_place_gone: null,
  remote_url: null,
  icon: null,
  icon_color: null,
  worktree: { default: null, link: [], setup: [], setup_timeout_seconds: 0 },
};

/** The project named `name`: a registered one or General; undefined when it is gone. */
export function repoNamed(repos: RepoConfig[], name: string): RepoConfig | undefined {
  return name === GENERAL ? GENERAL_REPO : repos.find((r) => r.name === name);
}

/** What a project is called on screen. */
export function projectName(name: string): string {
  return name === GENERAL ? "General" : name;
}
