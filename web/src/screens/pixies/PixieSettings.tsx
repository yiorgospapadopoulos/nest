import { useEffect, useState } from "react";
import type {
  Autonomy,
  Effort,
  PermissionMode,
  Pixie,
  ProjectAccess,
  ReportSeverity,
  UpdatePixieBody,
} from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import {
  AGENT_DEFAULT,
  effortLabel,
  effortOptions,
  labelOf,
  modelOptions,
  NO_THINKING,
  permissionOptions,
  thinkingLevels,
  type Option,
} from "../chat/options.ts";
import { PickerSheet } from "../chat/PickerSheet.tsx";
import { AUTONOMY, optionsOf, PROJECT_ACCESS, REPORT_PUSH } from "./options.ts";

// Shown while the pixie keeps the agent default.
const DEFAULT = "Default";

// Thinking back to the default: none chosen for the pixie.
const DEFAULT_THINKING: Option<string> = { value: null, label: DEFAULT };

interface Row {
  title: string;
  value: string;
  disabled?: boolean;
  options: Option<string>[];
  checked: string | null;
  // Null, from Default, is sent as null: the Mac sets the field back to the default.
  pick: (value: string | null) => UpdatePixieBody;
}

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => void;
}

/**
 * Model, thinking, permissions, project files, autonomy and which of its reports reach the
 * phone (B42): a value on the right that opens
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

  // The model the pixie runs, for its thinking levels and whether it takes Auto.
  const runs = pixie.model ?? state.agentDefaults?.model ?? null;
  const levels = thinkingLevels(models, runs);
  const rows: Row[] = [
    {
      title: "Model",
      value: pixie.model === null ? DEFAULT : labelOf("model", pixie.model, models),
      options: [AGENT_DEFAULT, ...modelOptions(models)],
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
      options: [DEFAULT_THINKING, ...effortOptions(levels)],
      checked: pixie.effort,
      pick: (effort) => ({ effort: effort as Effort | null }),
    },
    {
      title: "Permissions",
      value: labelOf("permission", pixie.permission_mode, models),
      options: permissionOptions(models, runs),
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
    {
      title: "Phone alerts",
      value: REPORT_PUSH[pixie.report_push].label,
      options: optionsOf(REPORT_PUSH),
      checked: pixie.report_push,
      pick: (push) => ({ report_push: push as ReportSeverity }),
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
            save(open.pick(value));
          }}
          onClose={() => {
            setOpen(null);
          }}
        />
      )}
    </div>
  );
}
