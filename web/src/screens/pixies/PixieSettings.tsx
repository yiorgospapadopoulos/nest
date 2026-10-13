import { useEffect, useState } from "react";
import type {
  Autonomy,
  Effort,
  PermissionMode,
  Pixie,
  ProjectAccess,
  UpdatePixieBody,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import {
  effortLabel,
  effortOptions,
  labelOf,
  modelOptions,
  NO_THINKING,
  PERMISSIONS,
  thinkingLevels,
  type Option,
} from "../chat/options.ts";
import { PickerSheet } from "../chat/PickerSheet.tsx";
import { AUTONOMY, optionsOf, PROJECT_ACCESS } from "./options.ts";

// Shown while the pixie keeps the agent default.
const DEFAULT = "Default";

interface Row {
  title: string;
  value: string;
  disabled?: boolean;
  options: Option<string>[];
  checked: string | null;
  pick: (value: string) => UpdatePixieBody;
}

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => void;
}

/**
 * Model, thinking, permissions, project files and autonomy: a value on the right that opens
 * a picker sheet. Model and thinking follow the composer's rules for an open chat.
 */
export function PixieSettings({ pixie, save }: Props) {
  const { state, actions } = useStore();
  const [open, setOpen] = useState<Row | null>(null);
  const models = state.models;
  const unknownModels = models === null;
  useEffect(() => {
    if (unknownModels) void actions.loadChoices();
  }, [unknownModels, actions]);

  // The model the pixie runs, for its thinking levels.
  const levels = thinkingLevels(models, pixie.model ?? state.agentDefaults?.model ?? null);
  const rows: Row[] = [
    {
      title: "Model",
      value: pixie.model === null ? DEFAULT : labelOf("model", pixie.model, models),
      options: modelOptions(models),
      checked: pixie.model,
      pick: (model) => ({ model }),
    },
    {
      title: "Thinking",
      value:
        levels.length === 0
          ? NO_THINKING
          : pixie.effort === null
            ? DEFAULT
            : effortLabel(pixie.effort),
      disabled: levels.length === 0,
      options: effortOptions(levels),
      checked: pixie.effort,
      pick: (effort) => ({ effort: effort as Effort }),
    },
    {
      title: "Permissions",
      value: labelOf("permission", pixie.permission_mode, models),
      options: PERMISSIONS,
      checked: pixie.permission_mode,
      pick: (mode) => ({ permission_mode: mode as PermissionMode }),
    },
    {
      title: "Project files",
      value: PROJECT_ACCESS[pixie.project_access].label,
      options: optionsOf(PROJECT_ACCESS),
      checked: pixie.project_access,
      pick: (access) => ({ project_access: access as ProjectAccess }),
    },
    {
      title: "Autonomy",
      value: AUTONOMY[pixie.autonomy].label,
      options: optionsOf(AUTONOMY),
      checked: pixie.autonomy,
      pick: (autonomy) => ({ autonomy: autonomy as Autonomy }),
    },
  ];

  return (
    <div className="lgrp gl pxgap">
      {rows.map((row) => (
        <button
          key={row.title}
          className="srow pxset"
          aria-haspopup="dialog"
          aria-label={`${row.title}: ${row.value}`}
          disabled={row.disabled === true}
          onClick={() => {
            setOpen(row);
          }}
        >
          <span>{row.title}</span>
          <span className="pxv">
            {row.value}
            <Icon name="chevr" className="chv" />
          </span>
        </button>
      ))}
      {open !== null && (
        <PickerSheet
          title={open.title}
          options={open.options}
          value={open.checked}
          onPick={(value) => {
            // Every option has a value: none of these offers "Default" (UpdatePixie skips nulls).
            save(open.pick(String(value)));
          }}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </div>
  );
}
