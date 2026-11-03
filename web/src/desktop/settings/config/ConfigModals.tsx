import { useMemo, useState, type ReactNode } from "react";
import { EditorSheet } from "./EditorSheet.tsx";
import { ServerFormSheet, SkillFormSheet } from "./FormSheets.tsx";
import {
  ConfigModalsContext,
  type ConfigForm,
  type ConfigModals,
  type EditTarget,
} from "./modals.ts";

/**
 * The editor sheet and the forms over Configuration or a project's tab, one at a time, as
 * ConfigurationSheets.swift's ConfigurationModals.
 */
export function ConfigModalsProvider({ children }: { children: ReactNode }) {
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [form, setForm] = useState<ConfigForm | null>(null);
  const modals = useMemo<ConfigModals>(
    () => ({
      edit: (target) => {
        setForm(null);
        setEditing(target);
      },
      form: (next) => {
        setEditing(null);
        setForm(next);
      },
    }),
    [],
  );
  const closeForm = () => {
    setForm(null);
  };
  return (
    <ConfigModalsContext value={modals}>
      {children}
      {editing !== null && (
        <EditorSheet
          key={editing.path}
          target={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
      {form !== null &&
        ("skill" in form ? (
          <SkillFormSheet
            repo={form.skill.repo}
            folder={form.skill.folder}
            onClose={closeForm}
            onCreated={modals.edit}
          />
        ) : (
          <ServerFormSheet
            initial={form.server}
            isNew={form.isNew}
            repo={form.repo}
            onClose={closeForm}
          />
        ))}
    </ConfigModalsContext>
  );
}
