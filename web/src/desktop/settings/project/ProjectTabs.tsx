import { useEffect, useState, type CSSProperties } from "react";
import type { Mascot, RepoConfig } from "../../../api/types.ts";
import { PIXIE_COLORS } from "../../../generated/mascots.ts";
import { MASCOTS } from "../../../screens/pixies/options.ts";
import { useStore } from "../../../store/context.ts";
import { Icon } from "../../../ui/Icon.tsx";
import { useApi } from "../../context.ts";
import { Sprite } from "../../pixies/Sprite.tsx";
import { useShell } from "../../shell/context.ts";
import { Button, Segmented } from "../../ui/controls.tsx";
import { SettingsRow, SettingsSection, Value } from "../rows.tsx";
import { AddField, Chips } from "./parts.tsx";
import { Dropdown } from "../rows.tsx";
import type { SaveProject } from "./useProjectSaver.ts";
import {
  addLink,
  addSetup,
  iconPatch,
  removeLink,
  removeSetup,
  setupTimeoutChoices,
  setupTimeoutLabel,
  worktreePatch,
} from "./worktree.ts";

// A project page's Chats, Worktrees, Look and Artifacts tabs, as ProjectPage.swift.

type WorkIn = "default" | "branch" | "worktree";
const WORK_IN: { value: WorkIn; label: string }[] = [
  { value: "default", label: "Follow default" },
  { value: "branch", label: "Current branch" },
  { value: "worktree", label: "New worktree" },
];
const workIn = (value: boolean | null): WorkIn =>
  value === null ? "default" : value ? "worktree" : "branch";

export function ChatsTab({ repo, save }: { repo: RepoConfig; save: SaveProject }) {
  return (
    <SettingsSection title="New chats in this project">
      <SettingsRow label="Work in">
        <Segmented
          label="Work in"
          value={workIn(repo.worktree.default)}
          options={WORK_IN}
          onChange={(value) => {
            const next = value === "default" ? null : value === "worktree";
            save(repo.name, (r) => worktreePatch(r.worktree, { ...r.worktree, default: next }));
          }}
        />
      </SettingsRow>
    </SettingsSection>
  );
}

export function WorktreesTab({ repo, save }: { repo: RepoConfig; save: SaveProject }) {
  const { actions } = useStore();
  const api = useApi();
  const config = repo.worktree;
  // Each change applies to the settings as last saved, not as this view shows them.
  const links = (change: (link: string[]) => string[]) => {
    save(repo.name, (r) =>
      worktreePatch(r.worktree, { ...r.worktree, link: change(r.worktree.link) }),
    );
  };
  const setup = (change: (setup: string[]) => string[]) => {
    save(repo.name, (r) =>
      worktreePatch(r.worktree, { ...r.worktree, setup: change(r.worktree.setup) }),
    );
  };
  const seconds = config.setup_timeout_seconds;
  // Gitignored files worth linking, read once per project (the Mac's first five).
  const [suggestions, setSuggestions] = useState<string[]>([]);
  useEffect(() => {
    let current = true;
    api.linkSuggestions(repo.name).then(
      (found) => {
        if (current) setSuggestions(found);
      },
      () => undefined,
    );
    return () => {
      current = false;
    };
  }, [api, repo.name]);
  const shownSuggestions = suggestions.filter((p) => !config.link.includes(p)).slice(0, 5);
  return (
    <SettingsSection title="When Nest makes a worktree">
      <SettingsRow label="Linked files">
        <Chips
          items={config.link}
          onRemove={(_, path) => {
            links((link) => removeLink(link, path));
          }}
        />
      </SettingsRow>
      <AddField
        label="Linked file"
        placeholder="Path in the project, such as .env"
        onAdd={(text) => {
          if (addLink(config.link, text) === null) {
            actions.toast("Use a path inside the project that is not linked yet", "error");
            return false;
          }
          links((link) => addLink(link, text) ?? link);
          return true;
        }}
      />
      {shownSuggestions.length > 0 && (
        <div className="dkp-suggest">
          <span>Suggested</span>
          {shownSuggestions.map((path) => (
            <Button
              key={path}
              kind="plain"
              onClick={() => {
                links((link) => addLink(link, path) ?? link);
                setSuggestions((list) => list.filter((p) => p !== path));
              }}
            >
              <Icon name="plus" />
              {path}
            </Button>
          ))}
        </div>
      )}
      <SettingsRow label="Setup commands">
        <Chips
          items={config.setup}
          onRemove={(index, command) => {
            setup((list) => removeSetup(list, command, index));
          }}
        />
      </SettingsRow>
      <AddField
        label="Setup command"
        placeholder="Command, such as npm ci"
        onAdd={(text) => {
          if (addSetup(config.setup, text) === null) return false;
          setup((list) => addSetup(list, text) ?? list);
          return true;
        }}
      />
      <SettingsRow label="Setup time limit">
        <Dropdown
          label="Setup time limit"
          title={setupTimeoutLabel(seconds)}
          width={130}
          items={() =>
            setupTimeoutChoices(seconds).map((choice) => ({
              title: setupTimeoutLabel(choice),
              checked: choice === seconds,
              onSelect: () => {
                save(repo.name, () => ({ setup_timeout_seconds: choice }));
              },
            }))
          }
        />
      </SettingsRow>
    </SettingsSection>
  );
}

// The default colour; saved as no colour, so it follows the default.
const STANDARD = "#8B7CF6";

export function LookTab({ repo, save }: { repo: RepoConfig; save: SaveProject }) {
  const color = repo.icon_color ?? STANDARD;
  const icon = (mascot: Mascot | null, iconColor: string | null) => {
    save(
      repo.name,
      (r) =>
        iconPatch(
          { icon: r.icon, icon_color: r.icon_color },
          { icon: mascot, icon_color: iconColor },
        ),
      "Could not save the project icon",
    );
  };
  return (
    <SettingsSection title="Icon">
      <SettingsRow label="Tab icon">
        <Segmented
          label="Tab icon"
          value={repo.icon === null ? "initials" : "sprite"}
          options={[
            { value: "initials", label: "Initials" },
            { value: "sprite", label: "Pixie sprite" },
          ]}
          onChange={(kind) => {
            icon(kind === "sprite" ? (repo.icon ?? MASCOTS[0] ?? null) : null, repo.icon_color);
          }}
        />
      </SettingsRow>
      {repo.icon !== null && (
        <SettingsRow label="Sprite">
          <span className="dkp-sprites" role="radiogroup" aria-label="Sprite">
            {MASCOTS.map((mascot) => (
              <button
                key={mascot}
                type="button"
                role="radio"
                aria-checked={repo.icon === mascot}
                aria-label={`Sprite ${mascot}`}
                title={mascot.charAt(0).toUpperCase() + mascot.slice(1)}
                className={repo.icon === mascot ? "dkp-sprite on" : "dkp-sprite"}
                onClick={() => {
                  icon(mascot, repo.icon_color);
                }}
              >
                <Sprite mascot={mascot} color={color} size={16} />
              </button>
            ))}
          </span>
        </SettingsRow>
      )}
      <SettingsRow label="Colour">
        <span
          className={repo.icon === null ? "dkp-swatches off" : "dkp-swatches"}
          role="radiogroup"
          aria-label="Colour"
        >
          {PIXIE_COLORS.map((preset) => (
            <button
              key={preset}
              type="button"
              role="radio"
              aria-checked={color.toUpperCase() === preset}
              aria-label={`Colour ${preset}`}
              title={preset}
              disabled={repo.icon === null}
              className="dkp-swatch"
              style={{ "--c": preset } as CSSProperties}
              onClick={() => {
                icon(repo.icon, preset === STANDARD ? null : preset);
              }}
            >
              <i />
            </button>
          ))}
        </span>
      </SettingsRow>
    </SettingsSection>
  );
}

/** How many artifacts the project's chats saved, and the Artifacts view (B79). */
export function ArtifactsTab({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const shell = useShell();
  const [count, setCount] = useState<number | null>(null);
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
    count === null || count === 0
      ? "None yet"
      : count === 1
        ? "1 artifact"
        : `${String(count)} artifacts`;
  return (
    <SettingsSection title="Artifacts">
      <SettingsRow label="Saved in this project">
        <Value text={text} />
        <Button
          onClick={() => {
            // The shell sets only the shown tab's view: another project's tab just opens
            // until the shell can open a named project's Artifacts view.
            if (shell.project === repo.name) {
              shell.setView("artifacts");
              shell.closeSettings();
            } else {
              shell.openProject(repo.name);
            }
          }}
        >
          Open Artifacts view
        </Button>
      </SettingsRow>
    </SettingsSection>
  );
}
