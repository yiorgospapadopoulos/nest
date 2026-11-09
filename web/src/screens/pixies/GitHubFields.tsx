import { useId } from "react";
import type { RepoConfig, TriggerAuthors } from "../../api/types.ts";
import {
  AUTHORS,
  GITHUB_EVENTS,
  GITHUB_NOTE,
  OUTSIDERS_WARNING,
  toggled,
  type GitHubDraft,
} from "../../triggers/github.ts";

/**
 * The habit editor's GitHub triggers (B148): the events, then which projects, labels,
 * branches and authors count. With no project ticked, every project on GitHub does.
 */
export function GitHubFields({
  draft,
  repos,
  onChange,
}: {
  draft: GitHubDraft;
  repos: RepoConfig[];
  onChange: (draft: GitHubDraft) => void;
}) {
  const id = useId();
  const change = (patch: Partial<GitHubDraft>) => {
    onChange({ ...draft, ...patch });
  };
  const onGitHub = repos.filter((r) => r.git && r.remote_url !== null);
  return (
    <>
      <h3 className="pg-h">Also run on GitHub</h3>
      <div className="lgrp gl">
        {GITHUB_EVENTS.map((event) => (
          <label key={event.value} className="srow pxchk">
            <span id={`${id}-${event.value}`}>{event.label}</span>
            <input
              type="checkbox"
              aria-labelledby={`${id}-${event.value}`}
              checked={draft.events.includes(event.value)}
              onChange={() => {
                change({ events: toggled(draft.events, event.value) });
              }}
            />
          </label>
        ))}
      </div>
      {draft.events.length > 0 && (
        <>
          {onGitHub.length > 1 && (
            <>
              <h3 className="pg-h">Only in</h3>
              <div className="lgrp gl">
                {onGitHub.map((repo) => (
                  <label key={repo.name} className="srow pxchk">
                    <span id={`${id}-p-${repo.name}`}>{repo.name}</span>
                    <input
                      type="checkbox"
                      aria-labelledby={`${id}-p-${repo.name}`}
                      checked={draft.projects.includes(repo.name)}
                      onChange={() => {
                        change({ projects: toggled(draft.projects, repo.name) });
                      }}
                    />
                  </label>
                ))}
              </div>
            </>
          )}
          <div className="lgrp gl pxgap">
            <div className="srow qh">
              <label>
                Labels
                <input
                  value={draft.labels}
                  placeholder="Any"
                  autoComplete="off"
                  onChange={(event) => {
                    change({ labels: event.target.value });
                  }}
                />
              </label>
            </div>
            <div className="srow qh">
              <label>
                Branches
                <input
                  value={draft.branches}
                  placeholder="Any"
                  autoComplete="off"
                  onChange={(event) => {
                    change({ branches: event.target.value });
                  }}
                />
              </label>
            </div>
            <div className="srow">
              <label htmlFor={`${id}-from`}>From</label>
              <select
                id={`${id}-from`}
                className="ssel"
                value={draft.authors}
                onChange={(event) => {
                  change({ authors: event.target.value as TriggerAuthors });
                }}
              >
                {AUTHORS.map((authors) => (
                  <option key={authors.value} value={authors.value}>
                    {authors.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </>
      )}
      {draft.events.length > 0 && draft.authors !== "members" && (
        <p className="hint gnote acwarn">{OUTSIDERS_WARNING}</p>
      )}
      <p className="hint gnote">{GITHUB_NOTE}</p>
    </>
  );
}
