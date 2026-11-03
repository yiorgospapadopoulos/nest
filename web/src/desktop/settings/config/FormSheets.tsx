import { useState } from "react";
import type { McpTransport } from "../../../api/types.ts";
import {
  formServer,
  isValidSkillName,
  type ServerForm,
} from "../../../screens/settings/configText.ts";
import { useStore } from "../../../store/context.ts";
import { SheetFrame } from "../../sheets/SheetFrame.tsx";
import { Button, TextField } from "../../ui/controls.tsx";
import type { EditTarget } from "./modals.ts";
import { FormLine, LinesField, SegmentPicker } from "./parts.tsx";
import { Confirm } from "../../sheets/Alert.tsx";

// The Add server and New skill forms over Configuration or a project's tab (B97), as
// ConfigurationSheets.swift's ServerFormSheet and SkillFormSheet.

const KINDS: readonly (readonly [McpTransport, string])[] = [
  ["stdio", "Command"],
  ["http", "HTTP"],
  ["sse", "SSE"],
];

interface ServerProps {
  initial: ServerForm;
  isNew: boolean;
  // The project whose `.mcp.json` it goes to; none is Shared.
  repo: string | null;
  onClose: () => void;
}

/** Add server or Edit: a command with its arguments and environment, or a URL with headers. */
export function ServerFormSheet({ initial, isNew, repo, onClose }: ServerProps) {
  const { actions } = useStore();
  const [form, setForm] = useState(initial);
  const [removing, setRemoving] = useState(false);
  const spec = formServer(form);
  const name = form.name.trim();
  const set = (change: Partial<ServerForm>) => {
    setForm((before) => ({ ...before, ...change }));
  };

  const save = () => {
    if (spec === null) return;
    const saving =
      repo === null
        ? actions.putMcpServer(name, spec)
        : actions.putProjectMcpServer(repo, name, spec);
    void saving.then((done) => {
      if (done) onClose();
    });
  };
  const remove = () => {
    const removed =
      repo === null ? actions.deleteMcpServer(name) : actions.deleteProjectMcpServer(repo, name);
    void removed.then((done) => {
      if (done) onClose();
    });
  };

  return (
    <SheetFrame
      title={isNew ? "Add server" : `Edit ${form.name}`}
      width={520}
      onClose={onClose}
      footer={
        <>
          {!isNew && (
            <Button
              kind="danger"
              className="dkc-foot-start"
              onClick={() => {
                setRemoving(true);
              }}
            >
              Remove
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" disabled={spec === null} onClick={save}>
            {isNew ? "Add" : "Save"}
          </Button>
        </>
      }
    >
      <form
        className="dkc-form"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <p className="dkc-form-about">
          {repo === null
            ? "Nest writes it into every engine that uses shared MCP servers."
            : "Saved in the project's .mcp.json, which only Claude reads."}
        </p>
        <FormLine label="Name">
          {isNew ? (
            <TextField
              label="Name"
              placeholder="playwright"
              value={form.name}
              onChange={(value) => {
                set({ name: value });
              }}
            />
          ) : (
            <span className="mono">{form.name}</span>
          )}
        </FormLine>
        <FormLine label="Kind">
          <SegmentPicker
            label="Kind"
            options={KINDS}
            value={form.transport}
            onChange={(transport) => {
              set({ transport });
            }}
          />
        </FormLine>
        {form.transport === "stdio" ? (
          <>
            <FormLine label="Command">
              <TextField
                label="Command"
                placeholder="npx"
                value={form.command}
                onChange={(value) => {
                  set({ command: value });
                }}
              />
            </FormLine>
            <FormLine label="Arguments">
              <LinesField
                placeholder="One per line"
                value={form.args}
                onChange={(value) => {
                  set({ args: value });
                }}
              />
            </FormLine>
            <FormLine label="Environment">
              <LinesField
                placeholder="KEY=value, one per line"
                value={form.env}
                onChange={(value) => {
                  set({ env: value });
                }}
              />
            </FormLine>
          </>
        ) : (
          <>
            <FormLine label="URL">
              <TextField
                label="URL"
                placeholder="https://example.com/mcp"
                value={form.url}
                onChange={(value) => {
                  set({ url: value });
                }}
              />
            </FormLine>
            <FormLine label="Headers">
              <LinesField
                placeholder="Name: value, one per line"
                value={form.headers}
                onChange={(value) => {
                  set({ headers: value });
                }}
              />
            </FormLine>
          </>
        )}
        <button type="submit" hidden />
      </form>
      {removing && (
        <Confirm
          title={`Remove ${name}?`}
          message={
            repo === null
              ? "It is removed from every engine that uses shared MCP servers. A backup is kept."
              : "It is removed from the project's .mcp.json."
          }
          action="Remove"
          destructive
          onConfirm={remove}
          onClose={() => {
            setRemoving(false);
          }}
        />
      )}
    </SheetFrame>
  );
}

interface SkillProps {
  repo: string | null;
  // The skills folder it is made in.
  folder: string;
  onClose: () => void;
  // Opens the new SKILL.md.
  onCreated: (target: EditTarget) => void;
}

/** New skill: a name and a line saying when to use it; the new SKILL.md opens next. */
export function SkillFormSheet({ repo, folder, onClose, onCreated }: SkillProps) {
  const { actions } = useStore();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const valid = isValidSkillName(name);

  const create = () => {
    if (!valid) return;
    const made =
      repo === null
        ? actions.createSkill(name, description)
        : actions.createProjectSkill(repo, name, description);
    void made.then((done) => {
      if (!done) return;
      onClose();
      onCreated({
        path: `${folder}/${name}/SKILL.md`,
        title: name,
        note: repo === null ? "shared skill" : "project skill",
      });
    });
  };

  return (
    <SheetFrame
      title="New skill"
      width={460}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" disabled={!valid} onClick={create}>
            Create
          </Button>
        </>
      }
    >
      <form
        className="dkc-form"
        onSubmit={(event) => {
          event.preventDefault();
          create();
        }}
      >
        <p className="dkc-form-about">
          {repo === null
            ? "Made in the shared skills folder, so every engine can use it."
            : "Made in the project's .claude/skills, which only Claude reads."}
        </p>
        <FormLine label="Name">
          <TextField label="Name" placeholder="release-notes" value={name} onChange={setName} />
        </FormLine>
        <FormLine label="Description">
          <TextField
            label="Description"
            placeholder="When the agent should use it"
            value={description}
            onChange={setDescription}
          />
        </FormLine>
        {name !== "" && !valid && (
          <p className="dkc-form-bad">Lower case letters, digits and dashes only.</p>
        )}
        <button type="submit" hidden />
      </form>
    </SheetFrame>
  );
}
