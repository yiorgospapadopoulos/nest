import { useId, useState } from "react";
import type { McpServer, McpTransport } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { formServer, isValidSkillName, type ServerForm } from "./configText.ts";

// The Add server and New skill forms of Settings > Configuration and a project's page
// (B97, B102 item 31). A repo's go to its own `.mcp.json` and `.claude/skills`.

const KINDS: { value: McpTransport; label: string }[] = [
  { value: "stdio", label: "Command" },
  { value: "http", label: "HTTP" },
  { value: "sse", label: "SSE" },
];

function Field({
  label,
  value,
  onChange,
  placeholder,
  lines = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  lines?: boolean;
}) {
  const id = useId();
  return (
    <div className="cfg-field">
      <label htmlFor={id}>{label}</label>
      {lines ? (
        <textarea
          id={id}
          rows={3}
          value={value}
          placeholder={placeholder}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      ) : (
        <input
          id={id}
          value={value}
          placeholder={placeholder}
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </div>
  );
}

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
  const server = formServer(form);
  const name = form.name.trim();
  const set = (change: Partial<ServerForm>) => {
    setForm({ ...form, ...change });
  };

  const save = (spec: McpServer) =>
    (repo === null
      ? actions.putMcpServer(name, spec)
      : actions.putProjectMcpServer(repo, name, spec)
    ).then((done) => {
      if (done) onClose();
    });
  // Only a shared server is edited here; a project's are removed from its list.
  const remove = async () => {
    if (await actions.deleteMcpServer(name)) onClose();
  };

  return (
    <Sheet
      title={isNew ? "Add server" : `Edit ${form.name}`}
      onClose={onClose}
      leading={
        <button className="done" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        server === null ? (
          <button className="done cfg-save" disabled>
            {isNew ? "Add" : "Save"}
          </button>
        ) : (
          <button className="done cfg-save" onClick={() => void save(server)}>
            {isNew ? "Add" : "Save"}
          </button>
        )
      }
    >
      <div className="cfg-form">
        <p className="cfg-about">
          {repo === null
            ? "Nest writes it into every engine that uses shared MCP servers."
            : "Saved in the project's .mcp.json, which only Claude reads."}
        </p>
        {isNew && (
          <Field
            label="Name"
            value={form.name}
            placeholder="playwright"
            onChange={(value) => {
              set({ name: value });
            }}
          />
        )}
        <div className="mseg" role="group" aria-label="Kind">
          {KINDS.map((kind) => (
            <button
              key={kind.value}
              aria-pressed={form.transport === kind.value}
              onClick={() => {
                set({ transport: kind.value });
              }}
            >
              {kind.label}
            </button>
          ))}
        </div>
        {form.transport === "stdio" ? (
          <>
            <Field
              label="Command"
              value={form.command}
              placeholder="npx"
              onChange={(value) => {
                set({ command: value });
              }}
            />
            <Field
              label="Arguments"
              lines
              value={form.args}
              placeholder="One per line"
              onChange={(value) => {
                set({ args: value });
              }}
            />
            <Field
              label="Environment"
              lines
              value={form.env}
              placeholder="KEY=value, one per line"
              onChange={(value) => {
                set({ env: value });
              }}
            />
          </>
        ) : (
          <>
            <Field
              label="URL"
              value={form.url}
              placeholder="https://example.com/mcp"
              onChange={(value) => {
                set({ url: value });
              }}
            />
            <Field
              label="Headers"
              lines
              value={form.headers}
              placeholder="Name: value, one per line"
              onChange={(value) => {
                set({ headers: value });
              }}
            />
          </>
        )}
        {!isNew && (
          <button
            className="b b-no cfg-remove"
            onClick={() => {
              setRemoving(true);
            }}
          >
            Remove
          </button>
        )}
      </div>
      {removing && (
        <Confirm
          title={`Remove ${name}?`}
          about="It is removed from every engine that uses shared MCP servers. A backup is kept."
          action="Remove"
          onConfirm={() => void remove()}
          onClose={() => {
            setRemoving(false);
          }}
        />
      )}
    </Sheet>
  );
}

interface SkillProps {
  repo: string | null;
  // Called with the new skill's name once it is made.
  onCreated: (name: string) => void;
  onClose: () => void;
}

/** New skill: a name and a line saying when to use it; its SKILL.md opens next. */
export function SkillFormSheet({ repo, onCreated, onClose }: SkillProps) {
  const { actions } = useStore();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const valid = isValidSkillName(name);

  const create = () =>
    (repo === null
      ? actions.createSkill(name, description)
      : actions.createProjectSkill(repo, name, description)
    ).then((done) => {
      if (done) onCreated(name);
    });

  return (
    <Sheet
      title="New skill"
      onClose={onClose}
      leading={
        <button className="done" onClick={onClose}>
          Cancel
        </button>
      }
      trailing={
        <button className="done cfg-save" disabled={!valid} onClick={() => void create()}>
          Create
        </button>
      }
    >
      <div className="cfg-form">
        <p className="cfg-about">
          {repo === null
            ? "Made in the shared skills folder, so every engine can use it."
            : "Made in the project's .claude/skills, which only Claude reads."}
        </p>
        <Field label="Name" value={name} placeholder="release-notes" onChange={setName} />
        <Field
          label="Description"
          value={description}
          placeholder="When the agent should use it"
          onChange={setDescription}
        />
        {name !== "" && !valid && (
          <p className="cfg-bad">Lower case letters, digits and dashes only.</p>
        )}
      </div>
    </Sheet>
  );
}
