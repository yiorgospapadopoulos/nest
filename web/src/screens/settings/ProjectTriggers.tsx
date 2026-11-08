import { useCallback, useEffect, useId, useState } from "react";
import type { ChatTrigger, RepoConfig, TriggerActivity, TriggerAuthors } from "../../api/types.ts";
import { activityTime } from "../../format.ts";
import { useStore } from "../../store/context.ts";
import {
  activityText,
  AUTHORS,
  canSaveTrigger,
  EMPTY_TRIGGERS,
  GITHUB_EVENTS,
  newTriggerDraft,
  NO_REMOTE,
  toggled,
  TRIGGER_NOTE,
  triggerBody,
  triggerDraftOf,
  triggerSummary,
  type TriggerDraft,
} from "../../triggers/github.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { AddHeading } from "../pixies/AddHeading.tsx";
import { Section } from "./rows.tsx";

type Editing = { trigger: ChatTrigger | null } | null;

/** A project's GitHub triggers (B148): each starts a chat here when its events happen. */
export function ProjectTriggers({ repo }: { repo: RepoConfig }) {
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

  if (repo.remote_url === null) {
    return (
      <Section title="Triggers">
        <p className="srow hint">{NO_REMOTE}</p>
      </Section>
    );
  }
  return (
    <>
      <AddHeading
        title="Triggers"
        label="Add trigger"
        popup
        onAdd={() => {
          setEditing({ trigger: null });
        }}
      />
      <div className="lgrp gl">
        {triggers.length === 0 && <p className="srow hint">{EMPTY_TRIGGERS}</p>}
        {triggers.map((trigger) => {
          const last = activityText(activity[trigger.id], (iso) => activityTime(iso, new Date()));
          return (
            <div key={trigger.id} className="srow pxhab">
              <button
                className="pxdt pxhabb"
                onClick={() => {
                  setEditing({ trigger });
                }}
              >
                <b>{trigger.name}</b>
                <span>{triggerSummary(trigger)}</span>
                {last !== null && <small className="pxhabm">{last}</small>}
              </button>
              <button
                className="sw"
                role="switch"
                aria-checked={trigger.enabled}
                aria-label={`${trigger.name} on`}
                onClick={() => {
                  void actions.setTriggerOn(repo.name, trigger.id, !trigger.enabled);
                }}
              />
            </div>
          );
        })}
      </div>
      {editing !== null && (
        <TriggerEditor
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

function TriggerEditor({
  repo,
  trigger,
  onClose,
}: {
  repo: string;
  trigger: ChatTrigger | null;
  onClose: () => void;
}) {
  const id = useId();
  const { actions } = useStore();
  const [draft, setDraft] = useState<TriggerDraft>(() =>
    trigger === null ? newTriggerDraft() : triggerDraftOf(trigger),
  );
  const [saving, setSaving] = useState(false);
  const change = (patch: Partial<TriggerDraft>) => {
    setDraft((before) => ({ ...before, ...patch }));
  };
  const save = () => {
    if (!canSaveTrigger(draft) || saving) return;
    setSaving(true);
    void actions.saveTrigger(repo, trigger?.id ?? null, triggerBody(draft)).then((saved) => {
      setSaving(false);
      if (saved) onClose();
    });
  };
  return (
    <Sheet
      title={trigger === null ? "New trigger" : "Edit trigger"}
      full
      onClose={onClose}
      leading={
        <button className="done l" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        <button className="done" disabled={!canSaveTrigger(draft) || saving} onClick={save}>
          Save
        </button>
      }
    >
      <div className="pset pxhabe">
        <label htmlFor={`${id}-name`}>Name</label>
        <input
          id={`${id}-name`}
          className="rin2"
          value={draft.name}
          autoComplete="off"
          data-autofocus
          onChange={(event) => {
            change({ name: event.target.value });
          }}
        />
      </div>
      <h3 className="pg-h">When</h3>
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
      <h3 className="pg-h">Only if</h3>
      <div className="lgrp gl">
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
      <div className="pset pxhabe">
        <label htmlFor={`${id}-prompt`}>Start a chat with</label>
        <textarea
          id={`${id}-prompt`}
          className="rin2"
          rows={4}
          value={draft.prompt}
          placeholder="Find why the checks failed and fix it."
          onChange={(event) => {
            change({ prompt: event.target.value });
          }}
        />
      </div>
      <p className="hint gnote">{TRIGGER_NOTE}</p>
      {trigger !== null && (
        <div className="lgrp gl pxgap">
          <button
            className="pxrow-d pxdanger"
            onClick={() => {
              void actions.deleteTrigger(repo, trigger.id).then((deleted) => {
                if (deleted) onClose();
              });
            }}
          >
            <span className="pxdt">
              <b>Delete trigger</b>
            </span>
          </button>
        </div>
      )}
    </Sheet>
  );
}
