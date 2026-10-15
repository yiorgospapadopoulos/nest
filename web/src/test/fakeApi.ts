import { vi, type Mock } from "vitest";
import type { Api } from "../api/client.ts";
import {
  account,
  agentDefaults,
  commandList,
  detail,
  diff,
  habit,
  habitRun,
  limits,
  modelList,
  month,
  notificationSettings,
  pixie,
  repo,
  session,
  team,
} from "./fixtures.ts";

export type FakeApi = { [K in keyof Api]: Mock<Api[K]> };

/** Every API call resolves with a small, valid answer unless a test overrides it. */
export function fakeApi(): FakeApi {
  return {
    redeem: vi.fn<Api["redeem"]>().mockResolvedValue({
      token: "t",
      device: {
        id: "d1",
        name: "iPhone",
        is_local: false,
        created_at: "2026-10-06T10:00:00Z",
        last_seen_at: null,
        revoked_at: null,
      },
    }),
    repos: vi.fn<Api["repos"]>().mockResolvedValue([repo("todo-ui")]),
    removeRepo: vi.fn<Api["removeRepo"]>().mockResolvedValue(null),
    updateRepo: vi
      .fn<Api["updateRepo"]>()
      .mockImplementation((name, patch) =>
        Promise.resolve({ ...repo(name), worktree: { ...repo(name).worktree, ...patch } }),
      ),
    sessions: vi.fn<Api["sessions"]>().mockResolvedValue([]),
    session: vi.fn<Api["session"]>().mockResolvedValue(detail()),
    sessionEvents: vi.fn<Api["sessionEvents"]>().mockResolvedValue([]),
    createSession: vi.fn<Api["createSession"]>().mockResolvedValue(session({ id: "new" })),
    sendMessage: vi
      .fn<Api["sendMessage"]>()
      .mockResolvedValue({ ...session({ state: "running" }), queued_message: null }),
    interrupt: vi.fn<Api["interrupt"]>().mockResolvedValue(null),
    cancelQueued: vi.fn<Api["cancelQueued"]>().mockResolvedValue(null),
    sessionCommands: vi.fn<Api["sessionCommands"]>().mockResolvedValue(commandList()),
    repoCommands: vi.fn<Api["repoCommands"]>().mockResolvedValue(commandList({ source: "repo" })),
    files: vi.fn<Api["files"]>().mockResolvedValue({ files: [] }),
    updateSession: vi.fn<Api["updateSession"]>().mockResolvedValue(session()),
    deleteSession: vi.fn<Api["deleteSession"]>().mockResolvedValue(null),
    search: vi.fn<Api["search"]>().mockResolvedValue({ hits: [], indexing: false }),
    claudeChats: vi.fn<Api["claudeChats"]>().mockResolvedValue([]),
    claudeChatEvents: vi.fn<Api["claudeChatEvents"]>().mockResolvedValue([]),
    adoptClaudeChat: vi.fn<Api["adoptClaudeChat"]>(),
    setClaudeChatArchived: vi.fn<Api["setClaudeChatArchived"]>(),
    approvals: vi.fn<Api["approvals"]>().mockResolvedValue([]),
    resolveApproval: vi.fn<Api["resolveApproval"]>(),
    diff: vi.fn<Api["diff"]>().mockResolvedValue(diff()),
    approve: vi.fn<Api["approve"]>().mockResolvedValue(session({ state: "idle" })),
    reject: vi.fn<Api["reject"]>().mockResolvedValue(session()),
    feedback: vi.fn<Api["feedback"]>().mockResolvedValue(session({ state: "running" })),
    ciFeedback: vi.fn<Api["ciFeedback"]>().mockResolvedValue(null),
    rewindPreview: vi.fn<Api["rewindPreview"]>().mockResolvedValue({
      can_rewind: true,
      files_changed: ["app/form.tsx", "app/schema.ts"],
      insertions: 12,
      deletions: 3,
      error: null,
    }),
    rewind: vi.fn<Api["rewind"]>().mockResolvedValue(null),
    merge: vi.fn<Api["merge"]>().mockResolvedValue(session({ state: "closed" })),
    uploadAttachment: vi.fn<Api["uploadAttachment"]>(),
    connectors: vi.fn<Api["connectors"]>().mockResolvedValue([]),
    usageMonth: vi.fn<Api["usageMonth"]>((y, m) => Promise.resolve(month(y, m))),
    usageLimits: vi.fn<Api["usageLimits"]>().mockResolvedValue(limits()),
    refreshUsage: vi.fn<Api["refreshUsage"]>().mockResolvedValue(limits()),
    reportVisibility: vi.fn<Api["reportVisibility"]>().mockResolvedValue(null),
    vapidKey: vi.fn<Api["vapidKey"]>().mockResolvedValue({ public_key: "BAEC" }),
    subscribePush: vi.fn<Api["subscribePush"]>().mockResolvedValue(null),
    unsubscribePush: vi.fn<Api["unsubscribePush"]>().mockResolvedValue(null),
    testPush: vi.fn<Api["testPush"]>().mockResolvedValue({ sent: 1, failed: 0, removed: 0 }),
    notificationSettings: vi
      .fn<Api["notificationSettings"]>()
      .mockResolvedValue(notificationSettings()),
    saveNotificationSettings: vi
      .fn<Api["saveNotificationSettings"]>()
      .mockImplementation((settings) => Promise.resolve(settings)),
    models: vi.fn<Api["models"]>().mockResolvedValue(modelList()),
    account: vi.fn<Api["account"]>().mockResolvedValue(account()),
    agentDefaults: vi.fn<Api["agentDefaults"]>().mockResolvedValue(agentDefaults()),
    saveAgentDefaults: vi
      .fn<Api["saveAgentDefaults"]>()
      .mockImplementation((defaults) => Promise.resolve(defaults)),
    pixies: vi.fn<Api["pixies"]>().mockResolvedValue([]),
    createPixie: vi.fn<Api["createPixie"]>().mockResolvedValue(pixie()),
    updatePixie: vi.fn<Api["updatePixie"]>().mockResolvedValue(pixie()),
    deletePixie: vi.fn<Api["deletePixie"]>().mockResolvedValue(null),
    reorderPixies: vi.fn<Api["reorderPixies"]>().mockResolvedValue([]),
    sendToPixie: vi
      .fn<Api["sendToPixie"]>()
      .mockResolvedValue(session({ pixie_id: "p1", repo: "pixie:p1" })),
    resetPixie: vi.fn<Api["resetPixie"]>().mockResolvedValue(pixie()),
    pixieFile: vi.fn<Api["pixieFile"]>().mockResolvedValue({ text: "", hash: "h" }),
    savePixieFile: vi.fn<Api["savePixieFile"]>().mockResolvedValue({ text: "", hash: "h" }),
    pixieNotes: vi.fn<Api["pixieNotes"]>().mockResolvedValue([]),
    pixieActivity: vi.fn<Api["pixieActivity"]>().mockResolvedValue([]),
    searchPixie: vi.fn<Api["searchPixie"]>().mockResolvedValue([]),
    duplicatePixie: vi.fn<Api["duplicatePixie"]>().mockResolvedValue(pixie({ id: "p2" })),
    teams: vi.fn<Api["teams"]>().mockResolvedValue([]),
    createTeam: vi.fn<Api["createTeam"]>().mockResolvedValue(team()),
    updateTeam: vi.fn<Api["updateTeam"]>().mockResolvedValue(team()),
    deleteTeam: vi.fn<Api["deleteTeam"]>().mockResolvedValue(null),
    habits: vi.fn<Api["habits"]>().mockResolvedValue([]),
    createHabit: vi
      .fn<Api["createHabit"]>()
      .mockImplementation((pixieId, body) =>
        Promise.resolve(habit({ ...body, pixie_id: pixieId })),
      ),
    updateHabit: vi
      .fn<Api["updateHabit"]>()
      .mockImplementation((pixieId, id, body) =>
        Promise.resolve(habit({ ...body, id, pixie_id: pixieId })),
      ),
    deleteHabit: vi.fn<Api["deleteHabit"]>().mockResolvedValue(null),
    runHabit: vi.fn<Api["runHabit"]>().mockResolvedValue(habitRun({ outcome: "queued" })),
    habitRuns: vi.fn<Api["habitRuns"]>().mockResolvedValue([]),
    pixieReports: vi.fn<Api["pixieReports"]>().mockResolvedValue([]),
    readReport: vi.fn<Api["readReport"]>().mockResolvedValue(null),
    readPixieReports: vi.fn<Api["readPixieReports"]>().mockResolvedValue(null),
  };
}
