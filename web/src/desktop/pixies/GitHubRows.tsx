// A habit editor's GitHub triggers (B148), as PixieHabitsPage.swift: the events, then
// their filters once one is chosen.
import { useStore } from "../../store/context.ts";
import {
  AUTHORS,
  authorsLabel,
  GITHUB_EVENTS,
  GITHUB_NOTE,
  projectsText,
  toggled,
  type GitHubDraft,
} from "../../triggers/github.ts";
import { CheckBox } from "../settings/rows.tsx";
import { DetailHeading, DetailNote, PickerRow } from "./parts.tsx";

export function GitHubRows({
  draft,
  change,
}: {
  draft: GitHubDraft;
  change: (patch: Partial<GitHubDraft>) => void;
}) {
  const { state } = useStore();
  const onGitHub = state.repos.filter((r) => r.git && r.remote_url !== null).map((r) => r.name);
  return (
    <>
      <DetailHeading title="Also runs on GitHub when" />
      {GITHUB_EVENTS.map((event) => {
        const on = draft.events.includes(event.value);
        return (
          <button
            key={event.value}
            className="pd-check"
            role="checkbox"
            aria-checked={on}
            onClick={() => {
              change({ events: toggled(draft.events, event.value) });
            }}
          >
            <CheckBox on={on} />
            {event.label}
          </button>
        );
      })}
      {draft.events.length > 0 && (
        <>
          <PickerRow
            title="Projects"
            value={projectsText(draft.projects)}
            items={() => [
              {
                title: "All projects",
                checked: draft.projects.length === 0,
                onSelect: () => {
                  change({ projects: [] });
                },
              },
              ...onGitHub.map((name) => ({
                title: name,
                checked: draft.projects.includes(name),
                onSelect: () => {
                  change({ projects: toggled(draft.projects, name) });
                },
              })),
            ]}
          />
          <FilterField
            title="Labels"
            placeholder="Any label"
            value={draft.labels}
            onChange={(labels) => {
              change({ labels });
            }}
          />
          <FilterField
            title="Branches"
            placeholder="Any branch"
            value={draft.branches}
            onChange={(branches) => {
              change({ branches });
            }}
          />
          <PickerRow
            title="From"
            value={authorsLabel(draft.authors)}
            items={() =>
              AUTHORS.map((authors) => ({
                title: authors.label,
                checked: draft.authors === authors.value,
                onSelect: () => {
                  change({ authors: authors.value });
                },
              }))
            }
          />
        </>
      )}
      <DetailNote text={GITHUB_NOTE} />
    </>
  );
}

/** A comma separated list, such as labels or branches. */
export function FilterField({
  title,
  placeholder,
  value,
  onChange,
}: {
  title: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="pd-timerow pd-filter">
      <span>{title}</span>
      <input
        className="pd-field"
        aria-label={title}
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    </label>
  );
}
