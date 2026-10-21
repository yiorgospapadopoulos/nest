import { useEffect, useState, type CSSProperties } from "react";
import type { RepoConfig, RepoPatch } from "../../api/types.ts";
import { PIXIE_COLORS } from "../../generated/mascots.ts";
import { useStore } from "../../store/context.ts";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { ArtifactsSheet } from "../artifacts/ArtifactsSheet.tsx";
import { projectScopes } from "../artifacts/view.ts";
import { ChipList } from "../pixies/ChipList.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { NameSheet } from "../pixies/NameSheet.tsx";
import { MASCOTS } from "../pixies/options.ts";
import { Sprite } from "../pixies/Sprite.tsx";
import { ProjectConfiguration } from "./ProjectConfiguration.tsx";
import { Row, Section, SegRow, SelectRow, type Choice } from "./rows.tsx";
import { withCurrent } from "./choices.ts";

type Tab = "General" | "Configuration" | "Chats" | "Worktrees" | "Look" | "Artifacts";

// Where the project's new chats work; null follows the agent default.
const WORK_IN: Choice<boolean | null>[] = [
  { value: null, label: "Follow default" },
  { value: false, label: "Current branch" },
  { value: true, label: "New worktree" },
];

// Setup command time limits offered, in minutes.
const SETUP_MINUTES = [5, 15, 30];

// A sprite icon's colour while the project has none of its own.
const SPRITE_COLOR = "#8B7CF6";

/** A project's page in Settings (B81), replacing the Project settings sheet. */
export function ProjectPage({ repo }: { repo: RepoConfig }) {
  // Chats and Worktrees are about git; a plain folder's chats work in place.
  const tabs: Tab[] = repo.git
    ? ["General", "Configuration", "Chats", "Worktrees", "Look", "Artifacts"]
    : ["General", "Configuration", "Look", "Artifacts"];
  const [tab, setTab] = useState<Tab>("General");
  return (
    <>
      <div className="ptabs" role="group" aria-label="Project settings">
        {tabs.map((t) => (
          <button
            key={t}
            aria-pressed={tab === t}
            onClick={() => {
              setTab(t);
            }}
          >
            {t}
          </button>
        ))}
      </div>
      <div>
        {tab === "General" && <General repo={repo} />}
        {tab === "Configuration" && <ProjectConfiguration repo={repo} />}
        {tab === "Chats" && <Chats repo={repo} />}
        {tab === "Worktrees" && <Worktrees repo={repo} />}
        {tab === "Look" && <Look repo={repo} />}
        {tab === "Artifacts" && <Artifacts repo={repo} />}
      </div>
    </>
  );
}

function General({ repo }: { repo: RepoConfig }) {
  return (
    <>
      <Section title="Project">
        <Row label="Name">
          <span className="sval">{repo.name}</span>
        </Row>
        <Row label="Folder">
          <span className="sval mono">{repo.path}</span>
        </Row>
        <Row label="Kind">
          <span className="sval">{repo.git ? "Git repository" : "Plain folder"}</span>
        </Row>
      </Section>
      {repo.git && <Git repo={repo} />}
      <RemoveProject repo={repo} />
    </>
  );
}

function Git({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const [branches, setBranches] = useState<string[] | null>(null);
  // The address typed, waiting for the user to confirm it.
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void actions.branches(repo.name).then((found) => {
      if (live && found !== null) setBranches(found);
    });
    return () => {
      live = false;
    };
  }, [actions, repo.name]);

  const current = repo.default_branch ?? "";
  const names = branches ?? [];
  const choices = (names.includes(current) ? names : [current, ...names]).map((b) => ({
    value: b,
    label: b,
  }));
  return (
    <Section title="Git">
      <SelectRow
        label="Default branch"
        value={current}
        choices={choices}
        onChange={(branch) => void actions.updateRepo(repo, { default_branch: branch })}
      />
      <Row label="Push to">
        <span className="sval mono">{repo.remote_url ?? "No remote yet"}</span>
        <button
          className="b"
          onClick={() => {
            setEditing(true);
          }}
        >
          {repo.remote_url === null ? "Set remote" : "Change"}
        </button>
      </Row>
      {editing && (
        <NameSheet
          title="Push to"
          label="Remote address"
          empty="Type the remote's address"
          initial={repo.remote_url ?? ""}
          action="Next"
          code
          onSave={(url) => {
            setEditing(false);
            setAsking(url);
          }}
          onClose={() => {
            setEditing(false);
          }}
        />
      )}
      {asking !== null && (
        <Confirm
          title={`Push ${repo.name} to ${asking}?`}
          about="Nest pushes this project only to this address."
          action="Push here"
          onConfirm={() => void actions.updateRepo(repo, { remote_url: asking })}
          onClose={() => {
            setAsking(null);
          }}
        />
      )}
    </Section>
  );
}

/** What removing the project does (B96: branches stay; only worktrees go), as the Mac says. */
function removal(chats: number): string {
  const folder = "Nest forgets this project. Its folder stays as it is.";
  if (chats === 0) return folder;
  return chats === 1
    ? `${folder} Its chat is deleted for good, with its worktree and history; its branch stays.`
    : `${folder} Its ${String(chats)} chats are deleted for good, with their worktrees and history; their branches stay.`;
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
    <Section title="Remove">
      <Row label={`Remove ${repo.name} from Nest`}>
        <button
          className="b b-no"
          onClick={() => {
            setAsking(true);
          }}
        >
          Remove
        </button>
      </Row>
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
              {removal(count)}
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
    </Section>
  );
}

function Chats({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const [busy, setBusy] = useState(false);
  return (
    <Section title="New chats in this project">
      <SegRow
        label="Work in"
        wide
        value={repo.worktree.default}
        choices={WORK_IN}
        disabled={busy}
        onChange={(value) => {
          setBusy(true);
          void actions.setWorktreeDefault(repo, value).finally(() => {
            setBusy(false);
          });
        }}
      />
    </Section>
  );
}

function Worktrees({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const save = (patch: RepoPatch) => actions.updateRepo(repo, patch);
  const minutes = Math.round(repo.worktree.setup_timeout_seconds / 60);
  return (
    <Section title="When Nest makes a worktree">
      <div className="srow col">
        <span className="slab">Linked files</span>
        <ChipList
          label="Linked files"
          items={repo.worktree.link}
          empty="None"
          save={(link) => save({ link })}
        />
      </div>
      <div className="srow col">
        <span className="slab">Setup commands</span>
        <ChipList
          label="Setup commands"
          items={repo.worktree.setup}
          empty="None"
          save={(setup) => save({ setup })}
        />
      </div>
      <SelectRow
        label="Setup time limit"
        value={minutes}
        choices={withCurrent(SETUP_MINUTES, minutes).map((m) => ({
          value: m,
          label: m === 1 ? "1 minute" : `${String(m)} minutes`,
        }))}
        onChange={(m) => void save({ setup_timeout_seconds: m * 60 })}
      />
    </Section>
  );
}

function Look({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const save = (patch: RepoPatch) => void actions.updateRepo(repo, patch);
  const color = repo.icon_color ?? SPRITE_COLOR;
  return (
    <Section title="Icon">
      <SegRow
        label="Tab icon"
        value={repo.icon === null ? "initials" : "sprite"}
        choices={[
          { value: "initials", label: "Initials" },
          { value: "sprite", label: "Pixie sprite" },
        ]}
        onChange={(kind) => {
          save({ icon: kind === "initials" ? null : (repo.icon ?? "bluebell") });
        }}
      />
      {repo.icon !== null && (
        <div className="srow col">
          <div className="pxpick" role="group" aria-label="Sprite">
            {MASCOTS.map((mascot) => (
              <button
                key={mascot}
                className="pxm"
                aria-label={mascot}
                aria-pressed={repo.icon === mascot}
                onClick={() => {
                  save({ icon: mascot });
                }}
              >
                <Sprite mascot={mascot} color={color} size={28} />
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="srow col">
        <span className="slab" id="project-colour">
          Colour
        </span>
        <div className="pxpick" role="group" aria-labelledby="project-colour">
          <button
            className="pxdot pxdef"
            aria-label="Default colour"
            aria-pressed={repo.icon_color === null}
            onClick={() => {
              save({ icon_color: null });
            }}
          />
          {PIXIE_COLORS.map((c) => (
            <button
              key={c}
              className="pxdot"
              style={{ "--px": c } as CSSProperties}
              aria-label={`Colour ${c}`}
              aria-pressed={repo.icon_color === c}
              onClick={() => {
                save({ icon_color: c });
              }}
            />
          ))}
        </div>
      </div>
    </Section>
  );
}

function Artifacts({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const [count, setCount] = useState<number | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    void actions.artifactCount(repo.name).then((found) => {
      if (live) setCount(found);
    });
    return () => {
      live = false;
    };
  }, [actions, repo.name]);
  const text =
    count === undefined
      ? "Loading..."
      : count === null || count === 0
        ? "None yet"
        : count === 1
          ? "1 artifact"
          : `${String(count)} artifacts`;
  return (
    <Section title="Artifacts">
      <Row label="Saved in this project">
        <span className="sval">{text}</span>
      </Row>
      <Row label="Artifacts view">
        <button
          className="b"
          onClick={() => {
            setOpen(true);
          }}
        >
          Open Artifacts view
        </button>
      </Row>
      {open && (
        <ArtifactsSheet
          scopes={projectScopes(repo.name)}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </Section>
  );
}
