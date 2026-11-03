import { createContext, use } from "react";
import type { ServerForm } from "../../../screens/settings/configText.ts";

/** A file to edit: its path, the sheet's title and a note such as "skill". */
export interface EditTarget {
  path: string;
  title: string;
  note: string | null;
}

/** A form over the page, as ConfigurationSheets.swift's ConfigurationForm. */
export type ConfigForm =
  // Add or edit a server; a project's go to its `.mcp.json`.
  | { server: ServerForm; isNew: boolean; repo: string | null }
  // A new skill in the shared folder, or a project's `.claude/skills`.
  | { skill: { repo: string | null; folder: string } };

/** What the page's parts ask the sheets over it to open (ConfigurationModals); the copy popup is the page's own. */
export interface ConfigModals {
  edit: (target: EditTarget) => void;
  form: (form: ConfigForm) => void;
}

export const ConfigModalsContext = createContext<ConfigModals | null>(null);

export function useConfigModals(): ConfigModals {
  const modals = use(ConfigModalsContext);
  if (modals === null) throw new Error("useConfigModals outside ConfigModalsProvider");
  return modals;
}
