import { useEffect, useId, useState } from "react";
import type { RepoConfig } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { ActionSheet, Sheet } from "../../ui/Sheet.tsx";

// Where the project's new chats work; null follows the agent default.
const MODES: { value: boolean | null; label: string }[] = [
  { value: null, label: "Agent default" },
  { value: true, label: "Worktree" },
  { value: false, label: "In place" },
];

/** One entry per line, blank lines and surrounding spaces left out. */
function lines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

interface Props {
  name: string;
  onClose: () => void;
}

/** A project's settings: where new chats work, worktree links and setup, and Remove. */
export function ProjectSettings({ name, onClose }: Props) {
  const { state } = useStore();
  const repo = state.repos.find((r) => r.name === name);
  // Removed, here or on the Mac.
  useEffect(() => {
    if (repo === undefined) onClose();
  }, [repo, onClose]);
  if (repo === undefined) return null;
  return (
    <Sheet title={repo.name} onClose={onClose}>
      <p className="note pset-path">{repo.path}</p>
      {repo.git ? (
        <>
          <WorktreeDefault repo={repo} />
          <WorktreeSetup repo={repo} />
        </>
      ) : (
        <p className="note">A plain folder: its chats work in place.</p>
      )}
      <RemoveProject repo={repo} />
    </Sheet>
  );
}

function WorktreeDefault({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const [busy, setBusy] = useState(false);
  const id = useId();
  return (
    <div className="lgrp gl">
      <div className="srow">
        <span id={id}>New chats work in</span>
        <div className="mseg" role="group" aria-labelledby={id}>
          {MODES.map(({ value, label }) => (
            <button
              key={label}
              aria-pressed={repo.worktree.default === value}
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void actions.setWorktreeDefault(repo, value).finally(() => {
                  setBusy(false);
                });
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function WorktreeSetup({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const [link, setLink] = useState(repo.worktree.link.join("\n"));
  const [setup, setSetup] = useState(repo.worktree.setup.join("\n"));
  const [busy, setBusy] = useState(false);
  const linkId = useId();
  const setupId = useId();
  const save = async () => {
    setBusy(true);
    const links = lines(link);
    const commands = lines(setup);
    if (await actions.saveRepoSetup(repo, links, commands)) {
      setLink(links.join("\n"));
      setSetup(commands.join("\n"));
    }
    setBusy(false);
  };
  return (
    <div className="lgrp gl pad pset">
      <label htmlFor={linkId}>Linked files</label>
      <textarea
        id={linkId}
        className="fin"
        rows={3}
        placeholder=".env"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        value={link}
        onChange={(event) => {
          setLink(event.target.value);
        }}
      />
      <p className="hint">
        Gitignored files of the project linked into each worktree, one path per line.
      </p>
      <label htmlFor={setupId}>Setup commands</label>
      <textarea
        id={setupId}
        className="fin"
        rows={3}
        placeholder="npm ci"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        value={setup}
        onChange={(event) => {
          setSetup(event.target.value);
        }}
      />
      <p className="hint">Run in each new worktree, one command per line.</p>
      <div className="acts">
        <button className="b b-pri" disabled={busy} onClick={() => void save()}>
          Save
        </button>
      </div>
    </div>
  );
}

function RemoveProject({ repo }: { repo: RepoConfig }) {
  const { state, actions } = useStore();
  const [asking, setAsking] = useState(false);
  // Open and archived chats; the daemon deletes them with the project.
  const chats = Object.values(state.sessions)
    .filter((s) => s.repo === repo.name)
    .map((s) => s.id);
  const count = chats.length;
  return (
    <>
      <div className="acts">
        <button
          className="b b-no"
          onClick={() => {
            setAsking(true);
          }}
        >
          Remove project
        </button>
      </div>
      {asking && (
        <ActionSheet
          label={`Remove ${repo.name}?`}
          role="alertdialog"
          onClose={() => {
            setAsking(false);
          }}
          title={
            <>
              <b>{`Remove ${repo.name}?`}</b>
              harness forgets this project. Its folder stays on your Mac, untouched.
              {count === 1 && " Its chat is deleted too, with its worktree and branch."}
              {count > 1 &&
                ` Its ${String(count)} chats are deleted too, with their worktrees and branches.`}
            </>
          }
        >
          <button
            className="asi dng mid"
            onClick={() => {
              setAsking(false);
              void actions.removeRepo(repo.name, chats);
            }}
          >
            Remove
          </button>
        </ActionSheet>
      )}
    </>
  );
}
