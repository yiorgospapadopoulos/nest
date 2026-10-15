import { useEffect, useId, useState } from "react";
import type { RepoConfig, Session, SessionMode } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import type { ChatNav } from "./CommandSheets.tsx";
import { Composer, type NewChatPlace } from "./Composer.tsx";
import { Frame } from "./Frame.tsx";
import type { Option } from "./options.ts";
import { PickerSheet } from "./PickerSheet.tsx";

const TITLE = "Where the chat works";

interface Props {
  repo: string;
  onBack: () => void;
  onCreated: (session: Session) => void;
  nav: ChatNav;
}

/** A new chat in a project: it starts with its first message. */
export function NewChat({ repo: name, onBack, onCreated, nav }: Props) {
  const { state } = useStore();
  const repo = state.repos.find((r) => r.name === name);
  const [place, setPlace] = useState<NewChatPlace>({});
  return (
    <Frame title="New chat" back={name} onBack={onBack}>
      <div className="ch-tx">
        <div className="tx-empty">
          <Icon name="spark" />
          <b>New chat</b>
          <span>Describe the task. The agent starts when you send it.</span>
        </div>
      </div>
      {repo?.git === true && <PlaceChoice repo={repo} onChange={setPlace} />}
      <Composer repo={name} place={place} onCreated={onCreated} nav={nav} />
    </Frame>
  );
}

/**
 * Where the new chat works, chosen above the composer before its first message (B55): on
 * the folder's current branch, or in a new worktree that starts from that branch, under
 * an optional branch name.
 */
function PlaceChoice({
  repo,
  onChange,
}: {
  repo: RepoConfig;
  onChange: (place: NewChatPlace) => void;
}) {
  const { state, actions } = useStore();
  const [mode, setMode] = useState<SessionMode | null>(null);
  const [typed, setTyped] = useState("");
  const [open, setOpen] = useState(false);
  const id = useId();

  // The branch checked out in the folder may have changed since the list was read.
  useEffect(() => {
    void actions.refreshRepo(repo.name);
  }, [actions, repo.name]);

  const own = repo.worktree.default;
  const shownMode =
    mode ??
    (own === null ? (state.agentDefaults?.mode ?? "in_place") : own ? "worktree" : "in_place");
  const worktree = shownMode === "worktree";
  const base = repo.current_branch;
  const name = typed.trim();

  useEffect(() => {
    onChange({
      mode: shownMode,
      ...(worktree && base !== null ? { base } : {}),
      ...(worktree && name !== "" ? { branch: name } : {}),
    });
  }, [onChange, shownMode, worktree, base, name]);

  const inPlace: Option<SessionMode> = {
    value: "in_place",
    label: base === null ? "Work in this folder" : `Work on ${base}`,
    hint: base === null ? "Edits the project folder" : `Edits the project folder, on ${base}`,
  };
  const newWorktree: Option<SessionMode> = {
    value: "worktree",
    label: "New worktree",
    hint: "A separate copy of the project on its own new branch",
  };
  const shown = worktree ? newWorktree : inPlace;

  return (
    <div className="ncp">
      <button
        className="ncp-b"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${TITLE}: ${shown.label}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Icon name="branch" />
        <span>{shown.label}</span>
        <Icon name="chev" className="ncp-c" />
      </button>
      {worktree && (
        <>
          <label className="sr" htmlFor={id}>
            Branch name
          </label>
          <input
            id={id}
            className="ncp-n"
            placeholder="Branch name (optional)"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
            }}
          />
        </>
      )}
      {open && (
        <PickerSheet
          title={TITLE}
          options={[inPlace, newWorktree]}
          value={shownMode}
          onPick={(value) => {
            setMode(value === "worktree" ? "worktree" : "in_place");
          }}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}
