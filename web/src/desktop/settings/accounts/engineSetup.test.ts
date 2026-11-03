import { describe, expect, it } from "vitest";
import { acpProvider, claudeProvider, codexProvider } from "../../../test/fixtures.ts";
import { engineSetup, GIT_WARNING, NOT_ON_PATH, otherEngines } from "./engineSetup.ts";

// Ported from NestKit's MoreEnginesTests: one row per engine past Claude and Codex, its
// state in a word and its one action.
describe("More engines", () => {
  const gemini = acpProvider({
    name: "gemini",
    display_name: "Gemini CLI",
    signed_in: false,
    sign_in: "api_key",
    login_command: null,
  });
  const cursor = acpProvider({
    name: "cursor",
    display_name: "Cursor agent",
    state: "not_installed",
    installable: false,
    tested: false,
    git_guard: false,
    login_command: "agent login",
    state_detail: "Install Cursor's CLI first.",
  });

  it("lists every engine but Claude and Codex, in the daemon's order", () => {
    const setups = otherEngines([claudeProvider(), acpProvider(), gemini, codexProvider(), cursor]);
    expect(setups.map((s) => s.name)).toEqual(["opencode", "gemini", "cursor"]);
  });

  it("gives each engine its state and its one action", () => {
    const opencode = engineSetup(acpProvider());
    expect([opencode.state, opencode.action]).toEqual(["Ready", { kind: "none" }]);
    expect(opencode.ready).toBe(true);
    expect(opencode.gitWarning).toBeNull();
    expect(opencode.labels).toEqual([]);

    const out = engineSetup(acpProvider({ signed_in: false }));
    expect([out.state, out.action]).toEqual([
      "Signed out",
      { kind: "signIn", command: "opencode auth login" },
    ]);

    expect(engineSetup(gemini).action).toEqual({
      kind: "addKey",
      placeholder: "Paste your Gemini CLI API key",
    });
    expect(engineSetup({ ...gemini, signed_in: true }).action).toEqual({ kind: "removeKey" });
  });

  it("offers no Install for an engine the user installs, and Install again after a failure", () => {
    const mine = engineSetup(cursor);
    expect([mine.state, mine.action]).toEqual([NOT_ON_PATH, { kind: "none" }]);
    expect(mine.failure).toBeNull();
    expect(mine.labels).toEqual(["untested"]);
    expect(mine.gitWarning).toBe(GIT_WARNING);
    expect(engineSetup({ ...cursor, state: "ready", signed_in: false }).action).toEqual({
      kind: "signIn",
      command: "agent login",
    });

    expect(engineSetup(acpProvider({ state: "not_installed" })).action).toEqual({
      kind: "install",
      again: false,
    });
    const failed = engineSetup(
      acpProvider({ state: "install_failed", state_detail: "npm could not be reached" }),
    );
    expect([failed.state, failed.action]).toEqual([
      "Install failed",
      { kind: "install", again: true },
    ]);
    expect(failed.failure).toBe("npm could not be reached");
  });
});
