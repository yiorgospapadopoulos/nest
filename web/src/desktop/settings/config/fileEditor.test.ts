import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../api/client.ts";
import type { FileText } from "../../../api/types.ts";
import { FileEditor, type FileApi } from "./fileEditor.ts";

const PATH = "/home/me/.codex/AGENTS.md";

/** A daemon holding files by path, versions counting up, refusing a stale save with 409. */
function daemon() {
  const files = new Map<string, FileText>([[PATH, { path: PATH, text: "# Rules", version: "v1" }]]);
  let count = 1;
  const fail: { next: Error | null } = { next: null };
  let gate: Promise<void> | null = null;
  const api: FileApi & { configurationFile: ReturnType<typeof vi.fn> } = {
    configurationFile: vi.fn((path: string) =>
      Promise.resolve(files.get(path) ?? { path, text: "", version: null }),
    ),
    writeConfigurationFile: vi.fn(async (path: string, text: string, expected: string | null) => {
      if (gate !== null) await gate;
      if (fail.next !== null) {
        const error = fail.next;
        fail.next = null;
        throw error;
      }
      const now = files.get(path)?.version ?? null;
      if (now !== expected) {
        throw new ApiError(409, "changed", null, { current_version: now });
      }
      count += 1;
      const version = `v${String(count)}`;
      files.set(path, { path, text, version });
      return { version };
    }),
  };
  return {
    api,
    files,
    fail,
    changeOnDisk(text: string, version: string) {
      files.set(PATH, { path: PATH, text, version });
    },
    hold() {
      let open: () => void = () => undefined;
      gate = new Promise<void>((resolve) => {
        open = resolve;
      });
      return () => {
        gate = null;
        open();
      };
    },
  };
}

async function opened(fake = daemon()) {
  const editor = new FileEditor(fake.api, PATH);
  await editor.load();
  return { editor, fake };
}

// Ported from NestKit's ConfigFileEditorTests (ConfigurationTests.swift).
describe("the configuration file editor", () => {
  it("reads and saves the file, each save naming the version the last one made", async () => {
    const { editor, fake } = await opened();
    expect(editor.state.loaded).toBe(true);
    expect(editor.state.text).toBe("# Rules");
    expect(editor.dirty).toBe(false);
    editor.setText("# Rules\n- one");
    expect(editor.dirty).toBe(true);
    expect(await editor.save()).toBe(true);
    expect(editor.dirty).toBe(false);
    expect(fake.api.writeConfigurationFile).toHaveBeenLastCalledWith(PATH, "# Rules\n- one", "v1");
    editor.setText("# Rules\n- one\n- two");
    expect(await editor.save()).toBe(true);
    expect(fake.files.get(PATH)?.text).toBe("# Rules\n- one\n- two");
  });

  it("starts a missing file empty and creates it", async () => {
    const fake = daemon();
    const editor = new FileEditor(fake.api, "/new/AGENTS.md");
    await editor.load();
    expect(editor.state.text).toBe("");
    editor.setText("hello");
    expect(await editor.save()).toBe(true);
    expect(fake.api.writeConfigurationFile).toHaveBeenCalledWith("/new/AGENTS.md", "hello", null);
  });

  it("follows the disk while the draft is untouched", async () => {
    const { editor, fake } = await opened();
    fake.changeOnDisk("# Theirs", "v2");
    await editor.checkDisk();
    expect(editor.state.text).toBe("# Theirs");
    expect(editor.state.onDisk).toBeNull();
  });

  it("shows the changed-on-disk bar over edits, then Reload takes the disk", async () => {
    const { editor, fake } = await opened();
    editor.setText("# Mine");
    fake.changeOnDisk("# Theirs", "v2");
    await editor.checkDisk();
    expect(editor.state.onDisk?.text).toBe("# Theirs");
    expect(editor.state.text).toBe("# Mine");
    editor.reload();
    expect(editor.state.text).toBe("# Theirs");
    expect(editor.state.onDisk).toBeNull();
    expect(editor.dirty).toBe(false);
  });

  it("keeps mine and saves over the disk", async () => {
    const { editor, fake } = await opened();
    editor.setText("# Mine");
    fake.changeOnDisk("# Theirs", "v2");
    await editor.checkDisk();
    editor.keepMine();
    expect(editor.state.onDisk).toBeNull();
    expect(await editor.save()).toBe(true);
    expect(fake.files.get(PATH)?.text).toBe("# Mine");
  });

  it("shows the bar when a save is refused for a change on disk", async () => {
    const { editor, fake } = await opened();
    editor.setText("# Mine");
    fake.changeOnDisk("# Theirs", "v2");
    expect(await editor.save()).toBe(false);
    expect(editor.state.onDisk?.text).toBe("# Theirs");
    expect(editor.state.text).toBe("# Mine");
  });

  it("treats a conflict without a version as changed on disk", async () => {
    const { editor, fake } = await opened();
    editor.setText("# Mine");
    fake.changeOnDisk("# Theirs", "v2");
    fake.fail.next = new ApiError(409, "changed", null, { current_version: null });
    expect(await editor.save()).toBe(false);
    editor.reload();
    expect(editor.state.text).toBe("# Theirs");
    expect(editor.state.error).toBeNull();
  });

  it("shows the daemon's words for invalid text and stays open", async () => {
    const { editor, fake } = await opened();
    editor.setText("[model\n");
    fake.fail.next = new ApiError(422, "Invalid TOML at line 1");
    expect(await editor.save()).toBe(false);
    expect(editor.state.error).toBe("Invalid TOML at line 1");
    expect(editor.state.text).toBe("[model\n");
    expect(editor.state.onDisk).toBeNull();
    editor.setText('model = "o3"\n');
    expect(await editor.save()).toBe(true);
    expect(editor.state.error).toBeNull();
  });

  it("throws other failures, no longer saving", async () => {
    const { editor, fake } = await opened();
    fake.fail.next = new ApiError(500, "boom");
    await expect(editor.save()).rejects.toThrow("boom");
    expect(editor.state.saving).toBe(false);
  });

  it("sees no change in the same text, an unchanged version, or before it read", async () => {
    const { editor, fake } = await opened();
    await editor.checkDisk();
    expect(editor.state.onDisk).toBeNull();
    editor.setText("# Same");
    fake.changeOnDisk("# Same", "v3");
    await editor.checkDisk();
    expect(editor.state.onDisk).toBeNull();
    const unread = new FileEditor(fake.api, "x");
    await unread.checkDisk();
    expect(fake.api.configurationFile).not.toHaveBeenCalledWith("x");
  });

  it("does not check the disk while saving", async () => {
    const { editor, fake } = await opened();
    const open = fake.hold();
    editor.setText("# Mine");
    const saving = editor.save();
    expect(editor.state.saving).toBe(true);
    const reads = fake.api.configurationFile.mock.calls.length;
    await editor.checkDisk();
    expect(fake.api.configurationFile.mock.calls.length).toBe(reads);
    open();
    expect(await saving).toBe(true);
  });
});
