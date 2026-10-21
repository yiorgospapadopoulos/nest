import { useEffect, useState } from "react";
import type {
  Autonomy,
  Effort,
  PermissionMode,
  Pixie,
  ProjectAccess,
  UpdatePixieBody,
} from "../../api/types.ts";
import { CLAUDE, isSelected, supportsAuto, thinkingLevels } from "../../store/catalog.ts";
import { useStore } from "../../store/context.ts";
import { catalogFor, modelSections, modelTitle } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import { effortLabel, NO_THINKING, PERMISSIONS, type Option } from "../chat/options.ts";
import { PickerSheet } from "../chat/PickerSheet.tsx";
import { AUTONOMY, optionsOf, PROJECT_ACCESS } from "./options.ts";

// Thinking while the pixie has none chosen, as the Mac's row shows it.
const NO_EFFORT = "-";

interface Row {
  title: string;
  value: string;
  disabled?: boolean;
  options: Option<string>[];
  checked: string | null;
  pick: (value: string | null) => UpdatePixieBody;
}

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => void;
}

/**
 * Model, thinking, permissions, project files and autonomy: a value on the right that opens
 * a picker sheet. The model menu has a section per engine and choosing a model chooses its
 * engine (B91); thinking and permissions follow that engine's models, with no Default
 * entries (B94), as NestKit's PixieModelPicker.
 */
export function PixieSettings({ pixie, save }: Props) {
  const { state, actions } = useStore();
  const [open, setOpen] = useState<Row | "model" | null>(null);
  const unknownModels = state.modelLists[CLAUDE] === undefined;
  useEffect(() => {
    if (unknownModels) void actions.loadChoices();
  }, [unknownModels, actions]);

  const catalog = catalogFor(state, pixie.provider);
  // The model its runs ask for: its own, or its engine's default (B94).
  const runs = pixie.model ?? catalog.defaultModel;
  const levels = thinkingLevels(catalog, runs);
  const auto = supportsAuto(catalog, runs);
  const model = modelTitle(state, pixie.model, pixie.provider);
  const rows: Row[] = [
    {
      title: "Thinking",
      value:
        levels.length === 0
          ? NO_THINKING
          : pixie.effort === null
            ? NO_EFFORT
            : effortLabel(pixie.effort),
      disabled: levels.length === 0,
      options: levels.map((level) => ({ value: level, label: effortLabel(level) })),
      checked: pixie.effort,
      pick: (effort) => ({ effort: effort as Effort }),
    },
    {
      title: "Permissions",
      value:
        PERMISSIONS.find((o) => o.value === pixie.permission_mode)?.label ?? pixie.permission_mode,
      options: PERMISSIONS.filter((o) => auto || o.value !== "auto"),
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
  const close = () => {
    setOpen(null);
  };

  return (
    <div className="lgrp pxgap">
      <button
        className="srow pxset"
        aria-haspopup="dialog"
        aria-label={`Model: ${model}`}
        onClick={() => {
          setOpen("model");
        }}
      >
        <span>Model</span>
        <span className="pxv">
          {model}
          <Icon name="chevr" className="chv" />
        </span>
      </button>
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
      {open === "model" && <ModelSheet pixie={pixie} save={save} onClose={close} />}
      {open !== null && open !== "model" && (
        <PickerSheet
          title={open.title}
          options={open.options}
          value={open.checked}
          onPick={(value) => {
            save(open.pick(value));
          }}
          onClose={close}
        />
      )}
    </div>
  );
}

/**
 * The model menu: each engine's section with its plan or that it is not signed in, then
 * its real models; a list not loaded says models are unavailable. Choosing another
 * engine's model names that engine too.
 */
function ModelSheet({ pixie, save, onClose }: Props & { onClose: () => void }) {
  const { state } = useStore();
  const own = pixie.provider;
  return (
    <ActionSheet label="Model" title={<b>Model</b>} onClose={onClose}>
      {modelSections(state, own, true).map((section) => {
        const mine = section.provider === own;
        return (
          <div key={section.provider} role="group" aria-label={section.title} className="msec">
            <div className="msec-h">
              <span>{section.title}</span>
              {section.detail !== "" && <small>{section.detail}</small>}
            </div>
            {section.catalog.models.length === 0 && (
              <button className="asi" role="menuitem" disabled>
                Models unavailable
              </button>
            )}
            {section.catalog.models.map((option) => {
              const checked = mine && isSelected(section.catalog, option, pixie.model);
              return (
                <button
                  key={option.value}
                  className="asi"
                  role="menuitemradio"
                  aria-checked={checked}
                  data-autofocus={checked ? true : undefined}
                  onClick={() => {
                    save(
                      mine
                        ? { model: option.value }
                        : { provider: section.provider, model: option.value },
                    );
                    onClose();
                  }}
                >
                  <span>
                    <span>{option.display_name}</span>
                    <small>{option.description}</small>
                  </span>
                  <Icon name="check" className="ck2" />
                </button>
              );
            })}
          </div>
        );
      })}
    </ActionSheet>
  );
}
