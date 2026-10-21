import { describe, expect, it } from "vitest";
import { defined } from "../../test/defined.ts";
import { configurationPage, copyPreview, engineSection, skillItem } from "../../test/fixtures.ts";
import {
  copyIntro,
  copySections,
  engineLine,
  fileName,
  fixedCaption,
  formServer,
  isValidSkillName,
  itemDetail,
  itemTitle,
  missingNote,
  NEW_SERVER,
  offersCopy,
  rulesElsewhere,
  serverEngines,
  serverForm,
  shortList,
  shortPath,
  showsCodexSwitch,
  shownSkills,
  skillDetail,
  skillTag,
  skillsToggle,
  standaloneLine,
} from "./configText.ts";

const none = { instructions: false, skills: [], mcp_servers: [] };

describe("configuration words", () => {
  it("shortens a home folder and names a file", () => {
    expect(shortPath("/Users/me/.claude/skills")).toBe("~/.claude/skills");
    expect(shortPath("/Users/me")).toBe("~");
    expect(shortPath("/opt/homebrew/bin/claude")).toBe("/opt/homebrew/bin/claude");
    expect(fileName("/Users/me/.codex/AGENTS.md")).toBe("AGENTS.md");
    expect(fileName("")).toBe("");
  });

  it("shows four skills until asked for all", () => {
    const skills = ["a", "b", "c", "d", "e"].map((name) => skillItem({ name }));
    expect(shownSkills(skills, false).map((s) => s.name)).toEqual(["a", "b", "c", "d"]);
    expect(shownSkills(skills, true)).toHaveLength(5);
    expect(skillsToggle(5, false)).toBe("Show all 5");
    expect(skillsToggle(5, true)).toBe("Show fewer");
    expect(skillsToggle(4, false)).toBeNull();
  });

  it("says where a skill comes from", () => {
    expect(skillTag(skillItem())).toBe("yours");
    expect(skillTag(skillItem({ source: "synced" }))).toBe("claude.ai account");
    expect(skillTag(skillItem({ source: "plugin", plugin: "superpowers" }))).toBe(
      "plugin superpowers",
    );
    expect(skillTag(skillItem({ source: "plugin" }))).toBe("plugin");
    expect(skillTag(skillItem({ source: "engine_only", engine: "codex" }))).toBe("Codex only");
    expect(skillTag(skillItem({ source: "engine_only" }))).toBe("Codex only");
    expect(skillTag(skillItem({ source: "project" }))).toBe("project");
    expect(skillDetail(skillItem({ source: "engine_only", engine: "claude" }))).toBe(
      "Found in Claude's own skills folder",
    );
    expect(skillDetail(skillItem({ source: "engine_only" }))).toBe(
      "Found in Codex's own skills folder",
    );
    expect(skillDetail(skillItem({ description: null }))).toBe("");
    expect(skillDetail(skillItem())).toBe("Reviews a change");
  });

  it("offers the Codex switch for account skills and those Codex does not load", () => {
    expect(showsCodexSwitch(skillItem({ codex_enabled: null }))).toBe(false);
    expect(showsCodexSwitch(skillItem({ codex_enabled: true }))).toBe(false);
    expect(showsCodexSwitch(skillItem({ codex_enabled: false }))).toBe(true);
    expect(showsCodexSwitch(skillItem({ source: "synced", codex_enabled: true }))).toBe(true);
  });

  it("says what Shared lacks, and offers the copy only then", () => {
    expect(missingNote(none)).toBeNull();
    expect(missingNote({ instructions: true, skills: ["a", "b"], mcp_servers: ["c"] })).toBe(
      "Not in Shared yet: instructions, 2 skills, 1 MCP server",
    );
    expect(missingNote({ instructions: false, skills: ["a"], mcp_servers: ["b", "c"] })).toBe(
      "Not in Shared yet: 1 skill, 2 MCP servers",
    );
    expect(offersCopy(engineSection())).toBe(false);
    expect(
      offersCopy(engineSection({ missing_from_shared: { ...none, instructions: true } })),
    ).toBe(true);
  });

  it("describes the engine and a copy found on the Mac", () => {
    expect(engineLine(engineSection())).toBe("Claude Code 2.1.1, bundled with Nest");
    expect(engineLine(engineSection({ id: "codex", name: "Codex", bundled_version: null }))).toBe(
      "Codex, bundled with Nest",
    );
    expect(standaloneLine(engineSection())).toBeNull();
    expect(
      standaloneLine(
        engineSection({ standalone: { path: "/Users/me/bin/claude", version: "2.1" } }),
      ),
    ).toBe("Also on this Mac: ~/bin/claude 2.1");
    expect(
      standaloneLine(engineSection({ standalone: { path: "/opt/claude", version: null } })),
    ).toBe("Also on this Mac: /opt/claude");
  });

  it("captions the switches that cannot change", () => {
    expect(fixedCaption("claude", "skills")).toBe("Claude's own folder is the shared one");
    expect(fixedCaption("codex", "instructions")).toBe("Codex's own AGENTS.md is the shared one");
    expect(fixedCaption("claude", "instructions")).toBeNull();
  });

  it("names and counts the engine's own items", () => {
    const claude = engineSection();
    const codex = engineSection({ id: "codex", name: "Codex" });
    const item = (kind: Parameters<typeof itemTitle>[0], n: number | null, detail = null) => ({
      kind,
      count: n,
      detail,
      path: null,
      folder: false,
    });
    expect(itemTitle("commands")).toBe("Slash commands");
    expect(itemDetail(item("plugins", 8), claude)).toBe("8 installed");
    expect(itemDetail(item("plugins", null), codex)).toBe("Codex's own · none");
    expect(itemDetail(item("connectors", 6), claude)).toBe("claude.ai · 6");
    expect(itemDetail({ ...item("permissions", 3), detail: "14 allow · 2 deny" }, claude)).toBe(
      "14 allow · 2 deny",
    );
    expect(itemDetail({ ...item("hooks", 2), detail: "" }, claude)).toBe("2");
    expect(itemDetail(item("hooks", 0), claude)).toBe("none");
    expect(itemDetail(item("settings", null), claude)).toBeNull();
  });

  it("orders a server's engines", () => {
    const server = configurationPage().shared.mcp_servers[0];
    expect(serverEngines({ ...defined(server), engines: ["codex", "claude"] })).toEqual([
      "Claude",
      "Codex",
    ]);
  });

  it("finds Claude holding the rules while the shared file is empty", () => {
    const claude = engineSection({ missing_from_shared: { ...none, instructions: true } });
    const page = configurationPage({ engines: [claude] });
    expect(rulesElsewhere(page)).toBeNull();
    const missing = { path: "/a", exists: false, version: null };
    expect(rulesElsewhere({ ...page, shared: { ...page.shared, instructions: missing } })).toBe(
      claude,
    );
    const empty = {
      path: "/a",
      exists: true,
      version: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    };
    expect(rulesElsewhere({ ...page, shared: { ...page.shared, instructions: empty } })).toBe(
      claude,
    );
    expect(
      rulesElsewhere({
        shared: { ...page.shared, instructions: missing },
        engines: [engineSection()],
      }),
    ).toBeNull();
  });
});

describe("copy popup words", () => {
  it("says the instructions are replaced only when they are", () => {
    expect(copyIntro(copyPreview())).toBe(
      "Skills and MCP servers are added to what Shared already has. Only the instructions file is replaced.",
    );
    expect(copyIntro(copyPreview({ instructions: null }))).toBe(
      "Skills and MCP servers are added to what Shared already has.",
    );
  });

  it("lists what is added, skipped and kept", () => {
    const preview = copyPreview({
      skills: {
        add: ["release-notes", "swift-format-fix"],
        already: ["a", "b"],
        same_name: [
          { name: "changelog", reason: "Shared has a skill with this name" },
          { name: "x", reason: "Claude has it from plugin superpowers" },
          { name: "y", reason: "Claude has it from plugin superpowers" },
          { name: "z", reason: "Its folder could not be read" },
          { name: "w", reason: "Shared has a skill with this name" },
        ],
      },
      mcp_servers: {
        add: ["playwright"],
        already: ["context7", "serena"],
        not_convertible: [{ name: "linear", reason: "Codex cannot connect to SSE servers" }],
      },
      stays: ["plugins themselves", "hooks"],
    });
    expect(copySections(preview, "Claude")).toEqual([
      {
        title: "Skills",
        lead: "Add 2",
        names: "release-notes, swift-format-fix",
        notes: [
          "2 already in Shared, left as they are",
          "2 with the same name as shared ones (changelog, w): Shared keeps its own",
          "2 Claude already has from plugin superpowers (x, y): left as they are",
          "1 skipped (z): Its folder could not be read",
        ],
      },
      {
        title: "MCP servers",
        lead: "Add 1",
        names: "playwright",
        notes: [
          "context7 and serena already in Shared",
          "linear stays with Claude: Codex cannot connect to SSE servers",
        ],
      },
      { title: "Stays Claude only", lead: null, names: null, notes: ["Plugins themselves, hooks"] },
    ]);
  });

  it("says when there is nothing to add", () => {
    const preview = copyPreview({
      skills: {
        add: [],
        already: [],
        same_name: [{ name: "a", reason: "Shared has a skill with this name" }],
      },
      mcp_servers: { add: [], already: ["one"], not_convertible: [] },
      stays: [],
    });
    expect(copySections(preview, "Codex")).toEqual([
      {
        title: "Skills",
        lead: "Nothing to add",
        names: null,
        notes: ["1 with the same name as a shared one (a): Shared keeps its own"],
      },
      {
        title: "MCP servers",
        lead: "Nothing to add",
        names: null,
        notes: ["one already in Shared"],
      },
      { title: "Stays Codex only", lead: null, names: null, notes: [] },
    ]);
  });

  it("adds no note for servers Shared does not have yet", () => {
    const [, added] = copySections(
      copyPreview({ mcp_servers: { add: ["x"], already: [], not_convertible: [] } }),
      "Claude",
    );
    expect(added?.notes).toEqual([]);
  });

  it("shortens long lists", () => {
    expect(shortList(["a", "b", "c", "d", "e"])).toBe("a, b, c and 2 more");
  });
});

describe("skill names and server forms", () => {
  it("takes the names the daemon accepts", () => {
    expect(isValidSkillName("release-notes")).toBe(true);
    expect(isValidSkillName("2fa")).toBe(true);
    expect(isValidSkillName("")).toBe(false);
    expect(isValidSkillName("-x")).toBe(false);
    expect(isValidSkillName("Release")).toBe(false);
    expect(isValidSkillName("a".repeat(65))).toBe(false);
  });

  it("reads a command server into the form and back", () => {
    const form = serverForm("serena", {
      transport: "stdio",
      command: "uvx",
      args: ["serena", "start"],
      env: { B: "2", A: "1" },
    });
    expect(form).toEqual({
      name: "serena",
      transport: "stdio",
      command: "uvx",
      args: "serena\nstart",
      env: "A=1\nB=2",
      url: "",
      headers: "",
    });
    expect(formServer({ ...form, env: "A=1\n\nno separator\n=x\nB = 2 " })).toEqual({
      transport: "stdio",
      command: "uvx",
      args: ["serena", "start"],
      env: { A: "1", B: "2" },
    });
  });

  it("reads a URL server into the form and back", () => {
    const form = serverForm("docs", {
      transport: "http",
      url: "https://docs.example.com/mcp",
      headers: { Authorization: "Bearer x" },
    });
    expect(form.headers).toBe("Authorization: Bearer x");
    expect(form.command).toBe("");
    expect(form.args).toBe("");
    expect(formServer(form)).toEqual({
      transport: "http",
      url: "https://docs.example.com/mcp",
      headers: { Authorization: "Bearer x" },
    });
    expect(serverForm("x", { transport: "sse" }).url).toBe("");
  });

  it("is incomplete without a name, a command or a URL", () => {
    expect(formServer(NEW_SERVER)).toBeNull();
    expect(formServer({ ...NEW_SERVER, name: "x" })).toBeNull();
    expect(formServer({ ...NEW_SERVER, name: "x", transport: "sse" })).toBeNull();
  });
});
