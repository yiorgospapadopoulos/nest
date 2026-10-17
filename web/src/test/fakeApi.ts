import { vi, type Mock } from "vitest";
import type { Api } from "../api/client.ts";
import {
  account,
  agentDefaults,
  claudeAccount,
  claudeCode,
  artifact,
  artifactContent,
  artifactDetail,
  commandList,
  device,
  github,
  installedPlugin,
  marketplace,
  pluginDetails,
  pixieDefaults,
  storageUsage,
  stuckSettings,
  usageSettings,
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
import { defined } from "./defined.ts";

export type FakeApi = { [K in keyof Api]: Mock<Api[K]> };

/** Every API call resolves with a small, valid answer unless a test overrides it. */
export function fakeApi(): FakeApi {
  const fake: FakeApi = {
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
    repos: vi.fn<Api["repos"]>().mockResolvedValue([repo("cv-page")]),
    // The repo as the list has it, without counting a call to `repos`.
    repo: vi.fn<Api["repo"]>().mockImplementation(async (name) => {
      const listed = await defined(fake.repos.getMockImplementation())();
      return defined(listed.find((r) => r.name === name));
    }),
    removeRepo: vi.fn<Api["removeRepo"]>().mockResolvedValue(null),
    updateRepo: vi.fn<Api["updateRepo"]>().mockResolvedValue(repo("cv-page")),
    sessions: vi.fn<Api["sessions"]>().mockResolvedValue([]),
    session: vi.fn<Api["session"]>().mockResolvedValue(detail()),
    sessionEvents: vi.fn<Api["sessionEvents"]>().mockResolvedValue([]),
    createSession: vi.fn<Api["createSession"]>().mockResolvedValue(session({ id: "new" })),
    sendMessage: vi
      .fn<Api["sendMessage"]>()
      .mockResolvedValue({ ...session({ state: "running" }), queued_message: null }),
    interrupt: vi.fn<Api["interrupt"]>().mockResolvedValue(null),
    stopTask: vi.fn<Api["stopTask"]>().mockResolvedValue(null),
    cancelQueued: vi.fn<Api["cancelQueued"]>().mockResolvedValue(null),
    sendNow: vi.fn<Api["sendNow"]>().mockResolvedValue(null),
    resumeLimit: vi.fn<Api["resumeLimit"]>().mockResolvedValue(session()),
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
    feedback: vi.fn<Api["feedback"]>().mockResolvedValue(session({ state: "running" })),
    ciFeedback: vi.fn<Api["ciFeedback"]>().mockResolvedValue(null),
    rewindPreview: vi.fn<Api["rewindPreview"]>().mockResolvedValue({
      can_rewind: true,
      files_changed: ["app/form.tsx", "app/schema.ts"],
      insertions: 12,
      deletions: 3,
      error: null,
    }),
    rewind: vi.fn<Api["rewind"]>().mockResolvedValue({
      can_rewind: true,
      files_changed: ["app/form.tsx", "app/schema.ts"],
      insertions: 12,
      deletions: 3,
      error: null,
      restore: "code",
      text: null,
      attachments: [],
    }),
    fork: vi.fn<Api["fork"]>(),
    shell: vi.fn<Api["shell"]>(),
    remember: vi.fn<Api["remember"]>(),
    attachment: vi.fn<Api["attachment"]>(),
    merge: vi.fn<Api["merge"]>().mockResolvedValue(session({ state: "closed" })),
    uploadAttachment: vi.fn<Api["uploadAttachment"]>(),
    connectors: vi.fn<Api["connectors"]>().mockResolvedValue([]),
    usageMonth: vi.fn<Api["usageMonth"]>((y, m) => Promise.resolve(month(y, m))),
    usageLimits: vi.fn<Api["usageLimits"]>().mockResolvedValue(limits()),
    refreshUsage: vi.fn<Api["refreshUsage"]>().mockResolvedValue(limits()),
    restartService: vi.fn<Api["restartService"]>().mockResolvedValue({ restarting: true }),
    health: vi.fn<Api["health"]>().mockResolvedValue({ status: "ok", version: "0.1.0" }),
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
    pixieGroups: vi.fn<Api["pixieGroups"]>().mockResolvedValue({}),
    goals: vi.fn<Api["goals"]>().mockResolvedValue([]),
    sendAway: vi.fn<Api["sendAway"]>().mockResolvedValue([]),
    pixieCalls: vi.fn<Api["pixieCalls"]>().mockResolvedValue([]),
    agentTranscript: vi
      .fn<Api["agentTranscript"]>()
      .mockResolvedValue({ tool_use_id: "a1", prompt: null, messages: [], report: null }),
    branches: vi.fn<Api["branches"]>().mockResolvedValue({ branches: ["develop", "main"] }),
    storage: vi.fn<Api["storage"]>().mockResolvedValue(storageUsage()),
    storageSettings: vi
      .fn<Api["storageSettings"]>()
      .mockResolvedValue({ archive_after_days: null }),
    saveStorageSettings: vi
      .fn<Api["saveStorageSettings"]>()
      .mockImplementation((settings) => Promise.resolve(settings)),
    largeAttachments: vi.fn<Api["largeAttachments"]>().mockResolvedValue([]),
    deleteAttachment: vi.fn<Api["deleteAttachment"]>().mockResolvedValue(null),
    rebuildSearch: vi.fn<Api["rebuildSearch"]>().mockResolvedValue(null),
    usageSettings: vi.fn<Api["usageSettings"]>().mockResolvedValue(usageSettings()),
    saveUsageSettings: vi
      .fn<Api["saveUsageSettings"]>()
      .mockImplementation((settings) => Promise.resolve(settings)),
    stuckSettings: vi.fn<Api["stuckSettings"]>().mockResolvedValue(stuckSettings()),
    saveStuckSettings: vi
      .fn<Api["saveStuckSettings"]>()
      .mockImplementation((settings) => Promise.resolve(settings)),
    pixieDefaults: vi.fn<Api["pixieDefaults"]>().mockResolvedValue(pixieDefaults()),
    savePixieDefaults: vi
      .fn<Api["savePixieDefaults"]>()
      .mockImplementation((settings) => Promise.resolve(settings)),
    github: vi.fn<Api["github"]>().mockResolvedValue(github()),
    checkGithub: vi.fn<Api["checkGithub"]>().mockResolvedValue(github()),
    claudeAccount: vi.fn<Api["claudeAccount"]>().mockResolvedValue(claudeAccount()),
    claudeLogin: vi.fn<Api["claudeLogin"]>().mockResolvedValue(null),
    claudeLogout: vi
      .fn<Api["claudeLogout"]>()
      .mockResolvedValue(claudeAccount({ signed_in: false, email: null, plan: null })),
    claudeCode: vi.fn<Api["claudeCode"]>().mockResolvedValue(claudeCode()),
    installClaudeCode: vi.fn<Api["installClaudeCode"]>().mockResolvedValue(null),
    devices: vi
      .fn<Api["devices"]>()
      .mockResolvedValue([
        device({ id: "mac", name: "MacBook Air", is_local: true }),
        device({ id: "d1", name: "iPhone" }),
      ]),
    revokeDevice: vi.fn<Api["revokeDevice"]>().mockResolvedValue(null),
    pairingCode: vi
      .fn<Api["pairingCode"]>()
      .mockResolvedValue({ code: "ABCD2345", expires_at: "2026-10-06T10:10:00Z" }),
    plugins: vi.fn<Api["plugins"]>().mockResolvedValue([installedPlugin()]),
    skills: vi.fn<Api["skills"]>().mockResolvedValue([]),
    marketplaces: vi.fn<Api["marketplaces"]>().mockResolvedValue([marketplace()]),
    addMarketplace: vi.fn<Api["addMarketplace"]>().mockResolvedValue(null),
    removeMarketplace: vi.fn<Api["removeMarketplace"]>().mockResolvedValue(null),
    availablePlugins: vi.fn<Api["availablePlugins"]>().mockResolvedValue([]),
    pluginDetails: vi.fn<Api["pluginDetails"]>().mockResolvedValue(pluginDetails()),
    installPlugin: vi.fn<Api["installPlugin"]>().mockResolvedValue(null),
    uninstallPlugin: vi.fn<Api["uninstallPlugin"]>().mockResolvedValue(null),
    setPluginEnabled: vi.fn<Api["setPluginEnabled"]>().mockResolvedValue(null),
    artifacts: vi.fn<Api["artifacts"]>().mockResolvedValue([]),
    artifactsUnseen: vi.fn<Api["artifactsUnseen"]>().mockResolvedValue({ unseen: 0 }),
    artifact: vi
      .fn<Api["artifact"]>()
      .mockImplementation((id) => Promise.resolve(artifactDetail({ id }))),
    artifactVersion: vi
      .fn<Api["artifactVersion"]>()
      .mockImplementation((id, version) =>
        Promise.resolve(artifactContent({ artifact_id: id, version })),
      ),
    markArtifactSeen: vi
      .fn<Api["markArtifactSeen"]>()
      .mockImplementation((id) => Promise.resolve(artifact({ id, seen: true }))),
    deleteArtifact: vi.fn<Api["deleteArtifact"]>().mockResolvedValue(null),
  };
  return fake;
}
