import { describe, expect, it, vi } from "vitest";
import type { RepoConfig, RepoPatch } from "../../../api/types.ts";
import { repo } from "../../../test/fixtures.ts";
import { createSettingsSaver } from "./saveQueue.ts";
import { addLink, worktreePatch } from "./worktree.ts";

const start = (): RepoConfig => {
  const base = repo("todo-ui");
  return { ...base, worktree: { ...base.worktree, link: [".env.local"] } };
};

/** A daemon that applies each patch to its copy, waiting on `gate` when one is set. */
function daemon() {
  let stored = start();
  const sent: RepoPatch[] = [];
  let gate: Promise<void> | null = null;
  const send = vi.fn(async (_name: string, patch: RepoPatch) => {
    sent.push(patch);
    if (gate !== null) await gate;
    stored = {
      ...stored,
      ...(patch.icon === undefined ? {} : { icon: patch.icon }),
      worktree: { ...stored.worktree, ...(patch.link === undefined ? {} : { link: patch.link }) },
    };
    return stored;
  });
  return {
    send,
    sent,
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

const link = (path: string) => (r: RepoConfig) =>
  worktreePatch(r.worktree, {
    ...r.worktree,
    link: addLink(r.worktree.link, path) ?? r.worktree.link,
  });

// Ported from NestKit's ProjectSettingsTests (audit BUG-102).
describe("project settings saves", () => {
  it("saves quick changes in turn, each on top of the last save, losing none", async () => {
    const api = daemon();
    const shown = start();
    const saved: RepoConfig[] = [];
    const saver = createSettingsSaver(
      api.send,
      () => shown,
      (r) => saved.push(r),
    );
    const open = api.hold();
    const first = saver.change("todo-ui", link("a"));
    const second = saver.change("todo-ui", link("b"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    // The second waits its turn.
    expect(api.sent).toHaveLength(1);
    open();
    await first;
    await second;
    expect(api.sent).toEqual([{ link: [".env.local", "a"] }, { link: [".env.local", "a", "b"] }]);
    expect(saved.at(-1)?.worktree.link).toEqual([".env.local", "a", "b"]);
  });

  it("sends nothing when nothing changed, or when the project is gone", async () => {
    const api = daemon();
    const saver = createSettingsSaver(
      api.send,
      (name) => (name === "todo-ui" ? start() : undefined),
      () => undefined,
    );
    expect(await saver.change("todo-ui", link(".env.local"))).toEqual(start());
    expect(await saver.change("gone", () => ({ default: true }))).toBeNull();
    expect(api.send).not.toHaveBeenCalled();
  });

  it("keeps the project after a refused save, and the next change still saves", async () => {
    const api = daemon();
    api.send.mockRejectedValueOnce(new Error("bad link"));
    const saved: RepoConfig[] = [];
    const saver = createSettingsSaver(api.send, start, (r) => saved.push(r));
    await expect(saver.change("todo-ui", link("x"))).rejects.toThrow("bad link");
    expect(saved).toEqual([]);
    await saver.change("todo-ui", link("y"));
    expect(api.sent.at(-1)).toEqual({ link: [".env.local", "y"] });
  });

  it("saves an icon change in turn with a links change, sending only the icon", async () => {
    const api = daemon();
    const saver = createSettingsSaver(api.send, start, () => undefined);
    const open = api.hold();
    const links = saver.change("todo-ui", link("a"));
    const sprite = saver.change("todo-ui", () => ({ icon: "moth" }));
    open();
    await links;
    const after = await sprite;
    expect(api.sent.at(-1)).toEqual({ icon: "moth" });
    expect(after?.icon).toBe("moth");
    expect(after?.worktree.link).toEqual([".env.local", "a"]);
  });
});
