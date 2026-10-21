import { useCallback, useEffect, useId, useState, type KeyboardEvent } from "react";
import type { RepoConfig, Session, SessionMode } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Dot } from "../../ui/bits.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { RepoIcon } from "../projects/ProjectHeader.tsx";
import type { ChatNav } from "./CommandSheets.tsx";
import { Composer, type NewChatPlace } from "./Composer.tsx";
import type { Option } from "./options.ts";
import { PickerSheet } from "./PickerSheet.tsx";
import { age, question, questions, startLists, type Waiting } from "./start.ts";

const TITLE = "Where the chat works";

// "Waiting on you" shows this many rows, then "N more".
const FIRST = 3;

interface Props {
  repo: string;
  onBack: () => void;
  onCreated: (session: Session) => void;
  nav: ChatNav;
  // Opens a chat listed under Waiting on you or Recent.
  onOpen: (sessionId: string) => void;
}

/**
 * A new chat in a project, as the Mac's start screen (B90 design I) fitted to the phone
 * (B102): what waits on the user in this project and its latest chats, then the project and
 * a question in large type over the composer docked at the bottom. It starts with its first
 * message.
 */
export function NewChat({ repo: name, onBack, onCreated, nav, onOpen }: Props) {
  const { state } = useStore();
  const repo = state.repos.find((r) => r.name === name);
  const [workIn, setWorkIn] = useState<NewChatPlace>({});
  // A new worktree's optional branch name.
  const [typed, setTyped] = useState("");
  const worktree = workIn.mode === "worktree";
  const branch = typed.trim();
  const choose = useCallback((place: NewChatPlace) => {
    setWorkIn(place);
  }, []);
  // The next question each time the screen appears, never the same twice in a row.
  const [asked] = useState(() => questions.next());
  const { waiting, recent } = startLists(state, name);
  const [more, setMore] = useState(false);
  const shown = more ? waiting : waiting.slice(0, FIRST);
  const now = new Date();
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") onBack();
  };

  return (
    <section className="push nc" aria-label="New chat" onKeyDown={onKeyDown}>
      <header className="ch-h">
        <div className="ch-r1">
          <button className="back" aria-label={`Back to ${name}`} onClick={onBack} autoFocus>
            <Icon name="x" />
          </button>
        </div>
      </header>
      <div className="nc-b">
        {waiting.length > 0 && (
          <section className="nc-l" aria-label="Waiting on you">
            <h3 className="lbl">Waiting on you · {waiting.length}</h3>
            {shown.map((item) => (
              <WaitingRow key={item.id} item={item} onOpen={onOpen} />
            ))}
            {waiting.length > FIRST && !more && (
              <button
                className="nc-more"
                onClick={() => {
                  setMore(true);
                }}
              >
                {waiting.length - FIRST} more
              </button>
            )}
          </section>
        )}
        {recent.length > 0 && (
          <section className="nc-l" aria-label="Recent">
            <h3 className="lbl">Recent</h3>
            {recent.map((chat) => (
              <button
                key={chat.id}
                className="nc-r"
                onClick={() => {
                  onOpen(chat.id);
                }}
              >
                <span className="nc-t">{chat.title}</span>
                <span className="nc-a">{age(chat.updated_at, now)}</span>
              </button>
            ))}
          </section>
        )}
        <div className="nc-who">
          {repo !== undefined && <RepoIcon repo={repo} />}
          {name}
        </div>
        <h2 className="nc-q">{question(asked, name)}</h2>
      </div>
      {worktree && (
        <div className="nc-n">
          <BranchName value={typed} onChange={setTyped} />
        </div>
      )}
      <Composer
        repo={name}
        workIn={worktree && branch !== "" ? { ...workIn, branch } : workIn}
        place={repo?.git === true && <PlaceChoice repo={repo} onChange={choose} />}
        placeholder="Ask, build, / for commands…"
        onCreated={onCreated}
        nav={nav}
      />
    </section>
  );
}

/** One thing waiting on the user: the chat's dot and name over its Needs you line. */
function WaitingRow({ item, onOpen }: { item: Waiting; onOpen: (id: string) => void }) {
  return (
    <button
      className="nc-w"
      onClick={() => {
        onOpen(item.chat);
      }}
    >
      <Dot tone={item.tone} />
      <span className="nc-t">{item.title}</span>
      <span className="nc-m">{item.line}</span>
    </button>
  );
}

function BranchName({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const id = useId();
  return (
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
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
    </>
  );
}

/**
 * Where the new chat works, as quiet text next to the mic (B55, B102): on the folder's
 * current branch, or in a new worktree that starts from that branch.
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
  const [open, setOpen] = useState(false);

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

  useEffect(() => {
    onChange({ mode: shownMode, ...(worktree && base !== null ? { base } : {}) });
  }, [onChange, shownMode, worktree, base]);

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
    <>
      <button
        className="qt ncp-b"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`${TITLE}: ${shown.label}`}
        onClick={() => {
          setOpen(true);
        }}
      >
        <span>{shown.label}</span>
        <Icon name="chev" className="ncp-c" />
      </button>
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
    </>
  );
}
