import { useCallback, useEffect, useState } from "react";
import type { ChatTrigger, RepoConfig, TriggerActivity } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import {
  activityText,
  AUTHORS,
  canSaveTrigger,
  EMPTY_TRIGGERS,
  GITHUB_EVENTS,
  newTriggerDraft,
  NO_REMOTE,
  OUTSIDERS_WARNING,
  toggled,
  TRIGGER_MODES,
  TRIGGER_NOTE,
  triggerBody,
  triggerDraftOf,
  triggerProblem,
  triggerSummary,
  type TriggerDraft,
} from "../../../triggers/github.ts";
import { clockTime } from "../../pixies/habitText.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { Button, TextField, Toggle } from "../../ui/controls.tsx";
import { Checkbox, SegmentPicker } from "../config/parts.tsx";
import { Note, SettingsListRow, SettingsSection, WarningLine } from "../rows.tsx";

// A project's GitHub triggers (B148), as ProjectPage.swift's Triggers tab: each one starts
// a chat here when its events happen on GitHub.

type Editing = { trigger: ChatTrigger | null } | null;

export function TriggersTab({ repo }: { repo: RepoConfig }) {
  const { actions } = useStore();
  const [editing, setEditing] = useState<Editing>(null);
  const [activity, setActivity] = useState<Record<string, TriggerActivity>>({});
  const triggers = repo.triggers ?? [];

  const load = useCallback(() => {
    void actions.triggerActivity(repo.name).then((found) => {
      if (found !== null) setActivity(Object.fromEntries(found.map((a) => [a.trigger_id, a])));
    });
  }, [actions, repo.name]);
  useEffect(() => {
    load();
    return actions.onEvent((event) => {
      if (event.type === "trigger.activity" && event.payload.repo === repo.name) load();
    });
  }, [actions, load, repo.name]);

  const now = new Date();
  const enable = (trigger: ChatTrigger, enabled: boolean) => {
    void actions.setTriggerOn(repo.name, trigger.id, enabled);
  };
  return (
    <>
      <SettingsSection
        title="Triggers"
        tools={
          repo.remote_url !== null && (
            <Button
              kind="plain"
              onClick={() => {
                setEditing({ trigger: null });
              }}
            >
              Add trigger
            </Button>
          )
        }
      >
        {repo.remote_url === null && <Note>{NO_REMOTE}</Note>}
        {repo.remote_url !== null && triggers.length === 0 && <Note>{EMPTY_TRIGGERS}</Note>}
        {triggers.map((trigger) => {
          const last = activityText(activity[trigger.id], (iso) => clockTime(iso, now));
          return (
            <SettingsListRow
              key={trigger.id}
              title={trigger.name}
              detail={[triggerSummary(trigger), last].filter((p) => p !== null).join(" · ")}
              trailing={
                <>
                  <Button
                    kind="plain"
                    onClick={() => {
                      setEditing({ trigger });
                    }}
                  >
                    Edit
                  </Button>
                  <Toggle
                    label={`${trigger.name} on`}
                    checked={trigger.enabled}
                    onChange={(on) => {
                      enable(trigger, on);
                    }}
                  />
                </>
              }
            />
          );
        })}
      </SettingsSection>
      {editing !== null && (
        <TriggerSheet
          repo={repo.name}
          trigger={editing.trigger}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </>
  );
}

function TriggerSheet({
  repo,
  trigger,
  onClose,
}: {
  repo: string;
  trigger: ChatTrigger | null;
  onClose: () => void;
}) {
  const { actions } = useStore();
  const [draft, setDraft] = useState<TriggerDraft>(() =>
    trigger === null ? newTriggerDraft() : triggerDraftOf(trigger),
  );
  const [saving, setSaving] = useState(false);
  const change = (patch: Partial<TriggerDraft>) => {
    setDraft((before) => ({ ...before, ...patch }));
  };
  const problem = triggerProblem(draft);
  const save = () => {
    if (!canSaveTrigger(draft) || saving) return;
    setSaving(true);
    void actions.saveTrigger(repo, trigger?.id ?? null, triggerBody(draft)).then((saved) => {
      setSaving(false);
      if (saved) onClose();
    });
  };
  const remove = () => {
    if (trigger === null) return;
    void actions.deleteTrigger(repo, trigger.id).then((deleted) => {
      if (deleted) onClose();
    });
  };
  return (
    <SheetFrame
      title={trigger === null ? "New trigger" : "Edit trigger"}
      width={480}
      onClose={onClose}
      footer={
        <>
          {trigger !== null && (
            <Button kind="plain" className="dkp-delete" onClick={remove}>
              Delete
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button
            kind="primary"
            disabled={!canSaveTrigger(draft) || saving}
            title={problem ?? undefined}
            onClick={save}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="dkp-trigger">
        <TextField
          label="Name"
          placeholder="Fix failing CI on main"
          value={draft.name}
          onChange={(name) => {
            change({ name });
          }}
        />
        <h3 className="dkp-trigger-h">When</h3>
        {GITHUB_EVENTS.map((event) => (
          <Checkbox
            key={event.value}
            label={event.label}
            on={draft.events.includes(event.value)}
            onToggle={() => {
              change({ events: toggled(draft.events, event.value) });
            }}
          />
        ))}
        <h3 className="dkp-trigger-h">Only if</h3>
        <TextField
          label="Labels"
          placeholder="Labels, such as bug (any if empty)"
          value={draft.labels}
          onChange={(labels) => {
            change({ labels });
          }}
        />
        <TextField
          label="Branches"
          placeholder="Branches, such as main or release/* (any if empty)"
          value={draft.branches}
          onChange={(branches) => {
            change({ branches });
          }}
        />
        <SegmentPicker
          label="From"
          options={AUTHORS.map((a) => [a.value, a.label] as const)}
          value={draft.authors}
          onChange={(authors) => {
            change({ authors });
          }}
        />
        {draft.authors !== "members" && <WarningLine text={OUTSIDERS_WARNING} />}
        <h3 className="dkp-trigger-h">Runs with</h3>
        <SegmentPicker
          label="Runs with"
          options={TRIGGER_MODES.map((m) => [m.value, m.label] as const)}
          value={draft.mode}
          onChange={(mode) => {
            change({ mode });
          }}
        />
        <h3 className="dkp-trigger-h">Start a chat with</h3>
        <textarea
          className="dkc-lines dkp-trigger-prompt"
          aria-label="What the chat should do"
          placeholder="Find why the checks failed and fix it."
          value={draft.prompt}
          onChange={(event) => {
            change({ prompt: event.target.value });
          }}
        />
        <p className="dkp-none">{TRIGGER_NOTE}</p>
        {problem !== null && draft.name.trim() !== "" && <p className="dkp-none">{problem}</p>}
      </div>
    </SheetFrame>
  );
}
