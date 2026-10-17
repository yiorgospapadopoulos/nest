import Foundation
import Testing

@testable import NestKit

/// One API method: what it sends and a response it can read.
struct RouteCase: Sendable, CustomTestStringConvertible {
    let method: String
    let target: String
    let body: String?
    let response: String
    let call: @Sendable (APIClient) async throws -> Void

    var testDescription: String { "\(method) \(target)" }

    init(
        _ method: String, _ target: String, body: String? = nil, response: String = "{}",
        _ call: @escaping @Sendable (APIClient) async throws -> Void
    ) {
        self.method = method
        self.target = target
        self.body = body
        self.response = response
        self.call = call
    }

    static let sessionJSON = Fixture.text("session_detail")
    static let approvalJSON = Fixture.json(Fixture.approval("ap-perm"))
    static let repoJSON = Fixture.json(Fixture.repos[0])
    static let stuckJSON = """
        {"waiting_minutes": 15, "silent_minutes": 0, "repeated_calls": 4, "turn_minutes": 60}
        """
    static let defaultsJSON = """
        {"model": "opus", "effort": "high", "permission_mode": "default", "mode": "in_place"}
        """
    static let storageJSON = """
        {"total_bytes": 10, "chats_bytes": 4, "attachments_bytes": 3, "artifacts_bytes": 0,
         "other_bytes": 3}
        """
    static let githubJSON = """
        {"state": "signed_in", "login": "octo", "checked_at": "2026-10-17T09:00:00Z"}
        """
    static let claudeJSON = """
        {"signed_in": true, "email": "me@example.com", "organization": null, "plan": "max",
         "method": "claude.ai", "checked_at": "2026-10-17T09:00:00Z"}
        """
    static let pluginsJSON = """
        [{"id": "pdf@official", "name": "pdf", "marketplace": "official", "version": null,
          "enabled": true, "scope": "user", "description": "PDFs"}]
        """
    static let availableJSON = """
        [{"id": "pdf@official", "name": "pdf", "marketplace": "official", "description": null,
          "version": "1.0", "source": "official", "install_count": 12, "installed": true}]
        """
    static let detailsJSON = """
        {"id": "pdf@official", "name": "pdf", "marketplace": "official", "description": null,
         "source": "./pdf", "installed": false, "components": {
           "skills": {"count": 2, "names": ["a", "b"]}, "agents": {"count": 1, "names": ["c"]},
           "hooks": {"count": 0, "names": []}, "mcp_servers": {"count": 1, "names": ["d"]},
           "lsp_servers": {"count": 0, "names": []}}}
        """
    static let pixieJSON = Fixture.text("pixie")
    static let teamJSON = Fixture.text("pixie_team")
    static let habitJSON = PixieHabitsTests.habitJSON()
    static let runJSON = PixieHabitsTests.runJSON()
    static let reportJSON = PixieReportsTests.reportJSON()
    static let claudeChatJSON = """
        {"id": "c1", "repo": "cv-page", "title": "T", "cwd": "/r", "worktree": null,
         "created_at": "2026-10-06T09:00:00Z", "last_activity_at": "2026-10-06T09:00:00Z",
         "message_count": 1, "open_in_claude_code": false}
        """

    static let all: [RouteCase] = [
        RouteCase("GET", "/api/repos", response: Fixture.text("repos")) {
            _ = try await $0.repos()
        },
        RouteCase(
            "POST", "/api/repos", body: #"{"name":"cv","path":"/tmp/cv"}"#, response: repoJSON
        ) { _ = try await $0.registerRepo(path: "/tmp/cv", name: "cv") },
        RouteCase("POST", "/api/repos/cv-page/open", body: #"{"app":"vscode"}"#, response: "") {
            try await $0.openRepo("cv-page", in: .vscode)
        },
        RouteCase("GET", "/api/sessions?archived=false", response: Fixture.text("sessions")) {
            _ = try await $0.sessions(repo: nil, archived: false)
        },
        RouteCase("GET", "/api/sessions?repo=cv-page&archived=true", response: "[]") {
            _ = try await $0.sessions(repo: "cv-page", archived: true)
        },
        RouteCase("GET", "/api/sessions/s1", response: sessionJSON) {
            _ = try await $0.session("s1")
        },
        RouteCase(
            "GET", "/api/goals?repo=cv-page",
            response:
                #"[{"session_id": "s1", "tasks": [{"id": "1", "subject": "A", "description": null, "active_form": null, "status": "pending"}]}]"#
        ) { _ = try await $0.goals(repo: "cv-page") },
        RouteCase(
            "POST", "/api/sessions",
            body:
                #"{"attachment_ids":["a1"],"effort":"high","mode":"in_place","model":"opus","permission_mode":"plan","prompt":"Fix it","repo":"cv-page","title":"Fix"}"#,
            response: sessionJSON
        ) {
            _ = try await $0.createSession(
                CreateSessionRequest(
                    repo: "cv-page", prompt: "Fix it", title: "Fix", mode: .inPlace, model: "opus",
                    effort: .high, permissionMode: .plan, attachmentIDs: ["a1"]))
        },
        RouteCase(
            "POST", "/api/sessions",
            body:
                #"{"attachment_ids":[],"base":"dev","branch":"fix/login","mode":"worktree","prompt":"Go","repo":"cv-page"}"#,
            response: sessionJSON
        ) {
            _ = try await $0.createSession(
                CreateSessionRequest(
                    repo: "cv-page", prompt: "Go", mode: .worktree, base: "dev",
                    branch: "fix/login"))
        },
        RouteCase(
            "POST", "/api/sessions",
            body: #"{"attachment_ids":[],"prompt":"Go","repo":"cv-page"}"#,
            response: sessionJSON
        ) {
            _ = try await $0.createSession(CreateSessionRequest(repo: "cv-page", prompt: "Go"))
        },
        RouteCase(
            "PATCH", "/api/sessions/s1",
            body:
                #"{"archived":true,"model":"haiku","permission_mode":"default","pinned":true,"title":"New"}"#,
            response: sessionJSON
        ) {
            _ = try await $0.updateSession(
                "s1",
                UpdateSessionRequest(
                    model: "haiku", permissionMode: .default, title: "New", pinned: true,
                    archived: true))
        },
        RouteCase("PATCH", "/api/sessions/s1", body: #"{"effort":"xhigh"}"#, response: sessionJSON)
        { _ = try await $0.updateSession("s1", UpdateSessionRequest(effort: .xhigh)) },
        RouteCase("DELETE", "/api/sessions/s1?purge=true", response: "") {
            try await $0.deleteSession("s1")
        },
        RouteCase(
            "GET", "/api/sessions/s1/events?after=12", response: Fixture.text("session_events")
        ) {
            _ = try await $0.sessionEvents("s1", after: 12)
        },
        RouteCase(
            "POST", "/api/sessions/s1/messages", body: #"{"attachment_ids":["a1"],"text":"More"}"#,
            response: sessionJSON
        ) { _ = try await $0.sendMessage("s1", text: "More", attachmentIDs: ["a1"]) },
        RouteCase(
            "GET", "/api/sessions/s1/events?after=0&before=40&limit=100",
            response: Fixture.text("session_events")
        ) { _ = try await $0.sessionEvents("s1", after: 0, before: 40, limit: 100) },
        RouteCase(
            "POST", "/api/sessions/s1/messages",
            body: #"{"attachment_ids":[],"interrupt":true,"text":"Try again"}"#,
            response: sessionJSON
        ) {
            _ = try await $0.sendMessage(
                "s1", text: "Try again", attachmentIDs: [], interrupt: true)
        },
        RouteCase(
            "GET", "/api/search?q=zod%20form&limit=20",
            response: #"{"hits": [], "indexing": true}"#
        ) { _ = try await $0.search(query: "zod form", repo: nil, limit: 20) },
        RouteCase(
            "GET", "/api/search?q=zod&repo=cv-page&limit=5",
            response: #"{"hits": [], "indexing": false}"#
        ) { _ = try await $0.search(query: "zod", repo: "cv-page", limit: 5) },
        RouteCase("GET", "/api/models", response: Fixture.text("models")) {
            _ = try await $0.models()
        },
        RouteCase(
            "GET", "/api/account",
            response:
                #"{"display_name": "G", "email": null, "plan": "Claude Max", "organization": null}"#
        ) { _ = try await $0.account() },
        RouteCase("GET", "/api/agents/defaults", response: defaultsJSON) {
            _ = try await $0.agentDefaults()
        },
        RouteCase(
            "PUT", "/api/agents/defaults",
            body: #"{"effort":null,"mode":"worktree","model":null,"permission_mode":"plan"}"#,
            response: defaultsJSON
        ) {
            _ = try await $0.updateAgentDefaults(
                AgentDefaults(model: nil, effort: nil, permissionMode: .plan, mode: .worktree))
        },
        RouteCase("GET", "/api/stuck/settings", response: stuckJSON) {
            _ = try await $0.stuckSettings()
        },
        RouteCase(
            "PUT", "/api/stuck/settings",
            body:
                #"{"repeated_calls":4,"silent_minutes":0,"turn_minutes":60,"waiting_minutes":15}"#,
            response: stuckJSON
        ) {
            _ = try await $0.updateStuckSettings(
                StuckSettings(
                    waitingMinutes: 15, silentMinutes: 0, repeatedCalls: 4, turnMinutes: 60))
        },
        RouteCase("POST", "/api/sessions/s1/interrupt", response: "") {
            try await $0.interrupt("s1")
        },
        RouteCase("POST", "/api/sessions/s1/limit/resume", response: sessionJSON) {
            _ = try await $0.resumeLimit("s1")
        },
        RouteCase("POST", "/api/sessions/s1/tasks/toolu_01/stop", response: "") {
            try await $0.stopTask("s1", task: "toolu_01")
        },
        RouteCase(
            "POST", "/api/sessions/s1/open-in-claude-code",
            response: #"{"launcher": "/tmp/x.command", "warning": null}"#
        ) { _ = try await $0.openInClaudeCode("s1") },
        RouteCase("GET", "/api/pixies", response: "[" + pixieJSON + "]") {
            _ = try await $0.pixies()
        },
        RouteCase(
            "GET", "/api/pixies/skills",
            response: #"[{"name": "pdf:fill", "description": "Fills forms", "plugin": "pdf"}]"#
        ) { _ = try await $0.pixieSkills() },
        RouteCase(
            "POST", "/api/pixies", body: #"{"mascot":"owl","name":"Reviewer"}"#,
            response: pixieJSON
        ) { _ = try await $0.createPixie(CreatePixieRequest(name: "Reviewer", mascot: .owl)) },
        RouteCase(
            "PATCH", "/api/pixies/p1", body: #"{"hidden":true,"skills":["review"]}"#,
            response: pixieJSON
        ) {
            _ = try await $0.updatePixie(
                "p1", UpdatePixieRequest(skills: ["review"], hidden: true))
        },
        RouteCase(
            "PATCH", "/api/pixies/p1", body: #"{"effort":null,"model":null}"#,
            response: pixieJSON
        ) {
            _ = try await $0.updatePixie(
                "p1", UpdatePixieRequest(clearsModel: true, clearsEffort: true))
        },
        RouteCase(
            "PUT", "/api/pixies/order", body: #"{"ids":["p2","p1"]}"#,
            response: "[" + pixieJSON + "]"
        ) { _ = try await $0.reorderPixies(["p2", "p1"]) },
        RouteCase("DELETE", "/api/pixies/p1", response: "") { try await $0.deletePixie("p1") },
        RouteCase(
            "POST", "/api/pixies/p1/messages", body: #"{"text":"hi"}"#, response: sessionJSON
        ) { _ = try await $0.sendToPixie("p1", text: "hi") },
        RouteCase("POST", "/api/pixies/p1/reset", response: pixieJSON) {
            _ = try await $0.resetPixie("p1")
        },
        RouteCase(
            "GET", "/api/pixies/p1/files/soul", response: #"{"text": "I am", "hash": "h"}"#
        ) { _ = try await $0.pixieFile("p1", name: "soul") },
        RouteCase(
            "PUT", "/api/pixies/p1/files/notes/a", body: #"{"hash":null,"text":"x"}"#,
            response: #"{"text": "x", "hash": "h2"}"#
        ) { _ = try await $0.savePixieFile("p1", name: "notes/a", text: "x", hash: nil) },
        RouteCase("GET", "/api/pixies/p1/notes", response: #"["a", "b"]"#) {
            _ = try await $0.pixieNotes("p1")
        },
        RouteCase(
            "GET", "/api/pixies/p1/search?q=a%20b",
            response: #"[{"file": "MEMORY.md", "line": "- x"}]"#
        ) { _ = try await $0.searchPixie("p1", query: "a b") },
        RouteCase(
            "PATCH", "/api/pixies/p1", body: #"{"team_id":"t1"}"#, response: pixieJSON
        ) { _ = try await $0.updatePixie("p1", UpdatePixieRequest(teamID: "t1")) },
        RouteCase(
            "PATCH", "/api/pixies/p1", body: #"{"team_id":null}"#, response: pixieJSON
        ) { _ = try await $0.updatePixie("p1", UpdatePixieRequest(leavesTeam: true)) },
        RouteCase(
            "GET", "/api/pixies/p1/activity",
            response:
                #"[{"id": 1, "ts": "2026-10-14T21:00:00Z", "tool": "nudge", "session_id": "s1", "summary": "Stuck"}]"#
        ) { _ = try await $0.pixieActivity("p1") },
        RouteCase(
            "PATCH", "/api/pixies/p1", body: #"{"max_per_day":10,"max_running":3}"#,
            response: pixieJSON
        ) { _ = try await $0.updatePixie("p1", UpdatePixieRequest(maxRunning: 3, maxPerDay: 10)) },
        RouteCase("GET", "/api/pixies/p1/habits", response: "[\(habitJSON)]") {
            _ = try await $0.pixieHabits("p1")
        },
        RouteCase(
            "POST", "/api/pixies/p1/habits",
            body:
                #"{"enabled":true,"max_minutes":20,"name":"Check","prompt":"Look","schedule":null,"triggers":["failed"]}"#,
            response: habitJSON
        ) {
            _ = try await $0.createHabit(
                "p1",
                CreateHabitRequest(
                    name: "Check", prompt: "Look", schedule: nil, triggers: [.failed],
                    maxMinutes: 20))
        },
        RouteCase(
            "PATCH", "/api/pixies/p1/habits/h1", body: #"{"enabled":false}"#, response: habitJSON
        ) { _ = try await $0.updateHabit("p1", "h1", UpdateHabitRequest(enabled: false)) },
        RouteCase("DELETE", "/api/pixies/p1/habits/h1", response: "") {
            try await $0.deleteHabit("p1", "h1")
        },
        RouteCase("POST", "/api/pixies/p1/habits/h1/run", response: runJSON) {
            _ = try await $0.runHabit("p1", "h1")
        },
        RouteCase("GET", "/api/pixies/p1/habits/h1/runs", response: "[\(runJSON)]") {
            _ = try await $0.habitRuns("p1", "h1")
        },
        RouteCase("GET", "/api/pixie-reports?unread=true", response: "[\(reportJSON)]") {
            _ = try await $0.pixieReports(unread: true)
        },
        RouteCase("GET", "/api/pixie-reports?unread=false", response: "[]") {
            _ = try await $0.pixieReports(unread: false)
        },
        RouteCase("POST", "/api/pixie-reports/rep1/read", response: "") {
            try await $0.markReportRead("rep1")
        },
        RouteCase("POST", "/api/pixies/p1/reports/read", response: "") {
            try await $0.markPixieReportsRead("p1")
        },
        RouteCase("POST", "/api/pixies/p1/duplicate", response: pixieJSON) {
            _ = try await $0.duplicatePixie("p1")
        },
        RouteCase("GET", "/api/pixie-teams", response: "[" + teamJSON + "]") {
            _ = try await $0.pixieTeams()
        },
        RouteCase(
            "POST", "/api/pixie-teams", body: #"{"handle":"qa","name":"QA"}"#, response: teamJSON
        ) { _ = try await $0.createPixieTeam(CreatePixieTeamRequest(name: "QA", handle: "qa")) },
        RouteCase("POST", "/api/pixie-teams", body: #"{"name":"QA"}"#, response: teamJSON) {
            _ = try await $0.createPixieTeam(CreatePixieTeamRequest(name: "QA"))
        },
        RouteCase(
            "PATCH", "/api/pixie-teams/t1", body: #"{"handle":"qa-2","leader_id":"p2","name":"Q"}"#,
            response: teamJSON
        ) {
            _ = try await $0.updatePixieTeam(
                "t1", UpdatePixieTeamRequest(name: "Q", handle: "qa-2", leaderID: "p2"))
        },
        RouteCase("DELETE", "/api/pixie-teams/t1", response: "") {
            try await $0.deletePixieTeam("t1")
        },
        RouteCase(
            "GET", "/api/pixie-groups",
            response: "{\"s1\": [\(ChatPixieJSON.pixie("p1"))]}"
        ) { _ = try await $0.pixieGroups() },
        RouteCase("GET", "/api/sessions/s1/pixies", response: "[]") {
            _ = try await $0.chatPixies("s1")
        },
        RouteCase(
            "POST", "/api/sessions/s1/pixies/send-away", body: #"{"pixie_id":"p1"}"#,
            response: "[]"
        ) { _ = try await $0.sendAway("s1", SendAwayRequest(pixieID: "p1")) },
        RouteCase(
            "POST", "/api/sessions/s1/pixies/send-away", body: #"{"team_id":"t1"}"#,
            response: "[]"
        ) { _ = try await $0.sendAway("s1", SendAwayRequest(teamID: "t1")) },
        RouteCase(
            "GET", "/api/sessions/s1/pixies/p1/calls",
            response: "[\(ChatPixieJSON.work(ChatPixieJSON.call("k1")))]"
        ) { _ = try await $0.pixieCallWork("s1", pixie: "p1") },
        RouteCase(
            "GET", "/api/sessions/s1/agents/tu1/transcript",
            response: ChatPixieJSON.transcript("tu1")
        ) { _ = try await $0.agentTranscript("s1", toolUseID: "tu1") },
        RouteCase("GET", "/api/sessions/s1/diff", response: Fixture.text("diff")) {
            _ = try await $0.diff("s1")
        },
        RouteCase(
            "POST", "/api/sessions/s1/approve",
            body:
                #"{"commit_message":"Add zod","open_pr":true,"push":true}"#,
            response: sessionJSON
        ) { _ = try await $0.approve("s1", ApproveRequest(commitMessage: "Add zod")) },
        RouteCase(
            "POST", "/api/sessions/s1/approve",
            body:
                #"{"commit_message":"M","files":["a.txt"],"open_pr":false,"pr_body":"B","pr_title":"T","push":false}"#,
            response: sessionJSON
        ) {
            _ = try await $0.approve(
                "s1",
                ApproveRequest(
                    commitMessage: "M", files: ["a.txt"], push: false, openPR: false, prTitle: "T",
                    prBody: "B"))
        },
        RouteCase(
            "POST", "/api/sessions/s1/approve",
            body:
                #"{"commit_message":"M","expected_fingerprint":"f","expected_head":"c","open_pr":true,"push":true}"#,
            response: sessionJSON
        ) {
            _ = try await $0.approve(
                "s1",
                ApproveRequest(commitMessage: "M", expectedHead: "c", expectedFingerprint: "f"))
        },
        RouteCase(
            "POST", "/api/sessions/s1/feedback", body: #"{"text":"Use a DAG"}"#,
            response: sessionJSON
        ) { _ = try await $0.feedback("s1", text: "Use a DAG") },
        RouteCase(
            "POST", "/api/sessions/s1/merge", body: #"{"delete_branch":true,"method":"rebase"}"#,
            response: sessionJSON
        ) { _ = try await $0.merge("s1", MergeRequest(method: .rebase)) },
        RouteCase("POST", "/api/sessions/s1/pr/refresh", response: sessionJSON) {
            _ = try await $0.refreshPR("s1")
        },
        RouteCase("GET", "/api/approvals", response: Fixture.text("approvals")) {
            _ = try await $0.approvals(status: nil, project: nil)
        },
        RouteCase("GET", "/api/approvals?status=pending&project=cv-page", response: "[]") {
            _ = try await $0.approvals(status: .pending, project: "cv-page")
        },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body: #"{"always":true,"behavior":"allow","dismiss":false}"#, response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .allow(always: true)) },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body: #"{"always":false,"behavior":"deny","dismiss":false,"message":"No"}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .deny(message: "No")) },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body: #"{"always":false,"answers":{"Q?":["A","B"]},"dismiss":false}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .answer(["Q?": ["A", "B"]])) },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve", body: #"{"always":false,"dismiss":true}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .dismiss()) },
        RouteCase("GET", "/api/claude-chats", response: Fixture.text("claude_chats")) {
            _ = try await $0.claudeChats(repo: nil, includeAutomated: false)
        },
        RouteCase("GET", "/api/claude-chats?repo=cv-page&include_automated=true", response: "[]") {
            _ = try await $0.claudeChats(repo: "cv-page", includeAutomated: true)
        },
        RouteCase("GET", "/api/claude-chats/c1", response: claudeChatJSON) {
            _ = try await $0.claudeChat("c1")
        },
        RouteCase(
            "GET", "/api/claude-chats/c1/events", response: Fixture.text("claude_chat_events")
        ) { _ = try await $0.claudeChatEvents("c1") },
        RouteCase(
            "PUT", "/api/claude-chats/c1/archived", body: #"{"archived":true}"#,
            response: Fixture.text("claude_chat_archived")
        ) { _ = try await $0.setClaudeChatArchived("c1", archived: true) },
        RouteCase(
            "PUT", "/api/claude-chats/c1/archived", body: #"{"archived":false}"#,
            response: claudeChatJSON
        ) { _ = try await $0.setClaudeChatArchived("c1", archived: false) },
        RouteCase("POST", "/api/claude-chats/c1/adopt", response: sessionJSON) {
            _ = try await $0.adoptClaudeChat("c1")
        },
        RouteCase("GET", "/api/connectors", response: Fixture.text("connectors")) {
            _ = try await $0.connectors()
        },
        RouteCase(
            "GET", "/api/usage/month?year=2026&month=10", response: Fixture.text("usage_month")
        ) {
            _ = try await $0.usageMonth(year: 2026, month: 10)
        },
        RouteCase("GET", "/api/usage/limits", response: Fixture.text("usage_limits")) {
            _ = try await $0.usageLimits()
        },
        RouteCase("POST", "/api/usage/refresh", response: Fixture.text("usage_limits")) {
            _ = try await $0.refreshUsage()
        },
        RouteCase("GET", "/api/usage/settings", response: #"{"refresh_minutes": 3}"#) {
            _ = try await $0.usageSettings()
        },
        RouteCase(
            "PUT", "/api/usage/settings",
            body: #"{"refresh_minutes":0,"warn_notify":true,"warn_percent":80}"#,
            response: #"{"refresh_minutes": 0}"#
        ) { _ = try await $0.updateUsageSettings(UsageSettings(refreshMinutes: 0)) },
        RouteCase("GET", "/api/push/status", response: #"{"devices": 2}"#) {
            _ = try await $0.pushStatus()
        },
        RouteCase("GET", "/api/repos/cv-page/branches", response: #"{"branches": ["main"]}"#) {
            _ = try await $0.repoBranches("cv-page")
        },
        RouteCase("GET", "/api/storage", response: storageJSON) { _ = try await $0.storage() },
        RouteCase("GET", "/api/storage/settings", response: #"{"archive_after_days": null}"#) {
            _ = try await $0.storageSettings()
        },
        RouteCase(
            "PUT", "/api/storage/settings", body: #"{"archive_after_days":30}"#,
            response: #"{"archive_after_days": 30}"#
        ) { _ = try await $0.updateStorageSettings(StorageSettings(archiveAfterDays: 30)) },
        RouteCase(
            "GET", "/api/storage/attachments?limit=20",
            response:
                #"[{"id": "a1", "name": "big.png", "bytes": 9, "media_type": "image/png", "session_id": null, "session_title": null, "created_at": "2026-10-17T09:00:00Z"}]"#
        ) { _ = try await $0.largeAttachments(limit: 20) },
        RouteCase("DELETE", "/api/attachments/a1", response: "") {
            try await $0.deleteAttachment("a1")
        },
        RouteCase("POST", "/api/search/rebuild", response: "") { try await $0.rebuildSearch() },
        RouteCase("GET", "/api/pixie-settings", response: Fixture.json(PixieSettings())) {
            _ = try await $0.pixieSettings()
        },
        RouteCase(
            "PUT", "/api/pixie-settings", body: Fixture.json(PixieSettings()),
            response: Fixture.json(PixieSettings())
        ) { _ = try await $0.updatePixieSettings(PixieSettings()) },
        RouteCase(
            "GET", "/api/notifications/settings", response: #"{"pixie_report_level": "info"}"#
        ) { _ = try await $0.notificationRules() },
        RouteCase(
            "PUT", "/api/notifications/settings", body: #"{"pixie_report_level":"warn"}"#,
            response: #"{"pixie_report_level": "warn"}"#
        ) {
            var rules = NotificationRules()
            rules.pixieReportLevel = .warn
            _ = try await $0.updateNotificationRules(rules)
        },
        RouteCase("GET", "/api/accounts/github", response: githubJSON) {
            _ = try await $0.githubAccount()
        },
        RouteCase("POST", "/api/accounts/github/check", response: githubJSON) {
            _ = try await $0.checkGitHubAccount()
        },
        RouteCase("GET", "/api/accounts/claude", response: claudeJSON) {
            _ = try await $0.claudeLogin()
        },
        RouteCase("POST", "/api/accounts/claude/login", response: "") {
            try await $0.signInClaude()
        },
        RouteCase("POST", "/api/accounts/claude/logout", response: claudeJSON) {
            _ = try await $0.signOutClaude()
        },
        RouteCase(
            "GET", "/api/claude-code",
            response:
                #"{"installed": false, "path": null, "version": null, "bundled_version": "2.1.0"}"#
        ) { _ = try await $0.claudeCode() },
        RouteCase("POST", "/api/claude-code/install", response: "") {
            try await $0.installClaudeCode()
        },
        RouteCase("GET", "/api/extensions/plugins", response: pluginsJSON) {
            _ = try await $0.plugins()
        },
        RouteCase(
            "GET", "/api/extensions/skills",
            response: #"[{"name": "notes", "description": null, "path": "/s/notes"}]"#
        ) { _ = try await $0.standaloneSkills() },
        RouteCase(
            "GET", "/api/extensions/marketplaces",
            response: #"[{"name": "official", "kind": "github", "source": "a/b"}]"#
        ) { _ = try await $0.marketplaces() },
        RouteCase(
            "POST", "/api/extensions/marketplaces", body: #"{"source":"a/b"}"#, response: ""
        ) { try await $0.addMarketplace(source: "a/b") },
        RouteCase("DELETE", "/api/extensions/marketplaces/official", response: "") {
            try await $0.removeMarketplace("official")
        },
        RouteCase("GET", "/api/extensions/available", response: availableJSON) {
            _ = try await $0.availablePlugins()
        },
        RouteCase("GET", "/api/extensions/plugins/pdf@official/details", response: detailsJSON) {
            _ = try await $0.pluginDetails("pdf@official")
        },
        RouteCase("POST", "/api/extensions/plugins/pdf@official/install", response: "") {
            try await $0.installPlugin("pdf@official")
        },
        RouteCase("POST", "/api/extensions/plugins/pdf@official/uninstall", response: "") {
            try await $0.uninstallPlugin("pdf@official")
        },
        RouteCase(
            "PUT", "/api/extensions/plugins/pdf@official/enabled", body: #"{"enabled":false}"#,
            response: ""
        ) { try await $0.setPluginEnabled("pdf@official", enabled: false) },
        RouteCase(
            "POST", "/api/clients/visibility", body: #"{"client":"mac","visible":true}"#,
            response: ""
        ) { try await $0.reportVisibility(true, client: "mac") },
        RouteCase(
            "POST", "/api/pairing/codes",
            response: #"{"code": "4F7K-9QX2", "expires_at": "2026-10-06T09:05:00Z"}"#
        ) { _ = try await $0.createPairingCode() },
        RouteCase("GET", "/api/devices", response: Fixture.text("devices")) {
            _ = try await $0.devices()
        },
        RouteCase("DELETE", "/api/devices/dev-phone", response: "") {
            try await $0.revokeDevice("dev-phone")
        },
        RouteCase("GET", "/api/repos/cv-page/commands", response: commandsJSON) {
            _ = try await $0.repoCommands("cv-page")
        },
        RouteCase("GET", "/api/sessions/s1/commands", response: commandsJSON) {
            _ = try await $0.sessionCommands("s1")
        },
        RouteCase("GET", "/api/sessions/s1/files?q=src/a%20b", response: #"{"files": []}"#) {
            _ = try await $0.sessionFiles("s1", query: "src/a b")
        },
        RouteCase("DELETE", "/api/sessions/s1/queue/q9", response: "") {
            try await $0.cancelQueued("s1", queuedID: "q9")
        },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body: #"{"always":false,"decision":"approve","dismiss":false,"mode":"acceptEdits"}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .approvePlan()) },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body: #"{"always":false,"decision":"approve","dismiss":false,"mode":"auto"}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .approvePlan(mode: .auto)) },
        RouteCase("DELETE", "/api/repos/cv-page", response: "") {
            try await $0.removeRepo("cv-page", purgeSessions: false)
        },
        RouteCase("DELETE", "/api/repos/cv-page?purge_sessions=true", response: "") {
            try await $0.removeRepo("cv-page", purgeSessions: true)
        },
        RouteCase("PATCH", "/api/repos/cv-page", body: #"{"default":null}"#, response: repoJSON) {
            _ = try await $0.updateRepo(
                "cv-page",
                RepoPatch(from: WorktreeConfig(isDefault: true), to: WorktreeConfig()))
        },
        RouteCase(
            "PATCH", "/api/repos/cv-page", body: #"{"default":false,"link":[".env"]}"#,
            response: repoJSON
        ) {
            _ = try await $0.updateRepo(
                "cv-page",
                RepoPatch(
                    from: WorktreeConfig(setup: ["npm ci"]),
                    to: WorktreeConfig(isDefault: false, link: [".env"], setup: ["npm ci"])))
        },
        RouteCase("PATCH", "/api/repos/cv-page", body: #"{"setup":[]}"#, response: repoJSON) {
            _ = try await $0.updateRepo(
                "cv-page",
                RepoPatch(from: WorktreeConfig(setup: ["npm ci"]), to: WorktreeConfig()))
        },
        RouteCase(
            "PATCH", "/api/repos/cv-page", body: ##"{"icon":"frog","icon_color":"#3DDC84"}"##,
            response: repoJSON
        ) {
            _ = try await $0.updateRepo(
                "cv-page",
                RepoPatch(from: ProjectIcon(), to: ProjectIcon(mascot: .frog, color: "#3DDC84")))
        },
        RouteCase("PATCH", "/api/repos/cv-page", body: #"{"icon":null}"#, response: repoJSON) {
            _ = try await $0.updateRepo(
                "cv-page",
                RepoPatch(
                    from: ProjectIcon(mascot: .owl, color: "#3DDC84"),
                    to: ProjectIcon(color: "#3DDC84")))
        },
        RouteCase("PATCH", "/api/repos/cv-page", body: #"{"icon_color":null}"#, response: repoJSON)
        {
            _ = try await $0.updateRepo(
                "cv-page",
                RepoPatch(from: ProjectIcon(color: "#3DDC84"), to: ProjectIcon()))
        },
        RouteCase("GET", "/api/repos/cv-page/link-suggestions", response: #"[".env"]"#) {
            _ = try await $0.linkSuggestions("cv-page")
        },
        RouteCase(
            "PUT", "/api/repos/order", body: #"{"order":["llm-hunter","cv-page"]}"#,
            response: Fixture.text("repos")
        ) { _ = try await $0.reorderRepos(["llm-hunter", "cv-page"]) },
        RouteCase(
            "GET", "/api/sessions/s1/rewind?message=42&restore=code",
            response:
                #"{"can_rewind": true, "files_changed": ["a"], "insertions": 1, "deletions": 0}"#
        ) { _ = try await $0.rewindPreview("s1", message: 42, restore: .code) },
        RouteCase(
            "POST", "/api/sessions/s1/rewind", body: #"{"message":42,"restore":"both"}"#,
            response: #"{"can_rewind": true, "restore": "both", "text": "t", "attachments": []}"#
        ) { _ = try await $0.rewind("s1", message: 42, restore: .both) },
        RouteCase(
            "POST", "/api/sessions/s1/shell", body: #"{"command":"ls"}"#,
            response:
                #"{"command": "ls", "exit_code": 0, "output": "a", "truncated": false, "timed_out": false, "context": "c"}"#
        ) { _ = try await $0.runShell("s1", command: "ls") },
        RouteCase(
            "POST", "/api/sessions/s1/memory", body: #"{"scope":"user","text":"x"}"#,
            response: #"{"path": "/h/CLAUDE.md", "scope": "user", "line": "- x"}"#
        ) { _ = try await $0.saveMemory("s1", text: "x", scope: .user) },
        RouteCase("GET", "/api/attachments/img1", response: "png") {
            let data = try await $0.attachmentData("img1")
            #expect(data == Data("png".utf8))
        },
        RouteCase("POST", "/api/sessions/s1/queue/q9/send-now", response: "") {
            try await $0.sendQueuedNow("s1", queuedID: "q9")
        },
        RouteCase(
            "POST", "/api/sessions/s1/fork", body: #"{"message":42}"#,
            response: #"{"session": \#(sessionJSON), "text": "t", "attachments": []}"#
        ) { _ = try await $0.fork("s1", message: 42) },
        RouteCase("POST", "/api/sessions/s1/ci-feedback", response: "") {
            try await $0.ciFeedback("s1")
        },
        RouteCase(
            "POST", "/api/sessions/s1/approve",
            body:
                #"{"commit_message":"M","confirm_remote_url":"git@x:me/r.git","open_pr":true,"push":true}"#,
            response: sessionJSON
        ) {
            _ = try await $0.approve(
                "s1", ApproveRequest(commitMessage: "M", confirmRemoteURL: "git@x:me/r.git"))
        },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body:
                #"{"always":false,"decision":"keep_planning","dismiss":false,"message":"Smaller"}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .keepPlanning(note: "  Smaller\n")) },
        RouteCase(
            "POST", "/api/approvals/ap1/resolve",
            body: #"{"always":false,"decision":"keep_planning","dismiss":false}"#,
            response: approvalJSON
        ) { _ = try await $0.resolveApproval("ap1", .keepPlanning(note: "  ")) },
        RouteCase("GET", "/api/artifacts", response: "[\(artifactJSON)]") {
            _ = try await $0.artifacts(repo: nil, sessionID: nil, pixieID: nil)
        },
        RouteCase("GET", "/api/artifacts?repo=cv-page&session_id=s1&pixie_id=p1", response: "[]") {
            _ = try await $0.artifacts(repo: "cv-page", sessionID: "s1", pixieID: "p1")
        },
        RouteCase("GET", "/api/artifacts/unseen", response: #"{"unseen": 3}"#) {
            let unseen = try await $0.unseenArtifacts()
            #expect(unseen == 3)
        },
        RouteCase("GET", "/api/artifacts/a1", response: detailJSON) {
            let detail = try await $0.artifact("a1")
            #expect(detail.versions.map(\.version) == [1, 2])
        },
        RouteCase("GET", "/api/artifacts/a1/versions/2", response: contentJSON) {
            let content = try await $0.artifactContent("a1", version: 2)
            #expect(content.content == "<p>Hi</p>")
        },
        RouteCase("POST", "/api/artifacts/a1/seen", response: artifactJSON) {
            let seen = try await $0.markArtifactSeen("a1")
            #expect(seen.id == "a1")
        },
        RouteCase("DELETE", "/api/artifacts/a1", response: "") {
            try await $0.deleteArtifact("a1")
        },
    ]

    static let artifactJSON = Fixture.artifactJSON()
    static let detailJSON =
        String(artifactJSON.dropLast())
            + """
            , "versions": [
              {"version": 1, "title": "Options", "size": 1834, "created_at": "2026-10-17T09:30:00+00:00"},
              {"version": 2, "title": "Options compared", "size": 2210, "created_at": "2026-10-17T09:41:00+00:00"}]}
            """
    static let contentJSON = """
        {"artifact_id": "a1", "version": 2, "kind": "html", "title": "Options compared",
         "content": "<p>Hi</p>", "size": 9, "created_at": "2026-10-17T09:41:00+00:00"}
        """

    static let commandsJSON = """
        {"source": "session", "commands": [{"name": "compact", "description": "Compact",
         "argument_hint": "<instructions>"}], "agents": [{"name": "Explore", "description": null}],
         "updated_at": "2026-10-07T01:00:00Z"}
        """
}

@Suite struct APIClientTests {
    let transport = FakeTransport()
    var client: APIClient { APIClient(token: "tok-123", transport: transport) }

    @Test(arguments: RouteCase.all)
    func sendsTheRouteAndReadsItsResponse(route: RouteCase) async throws {
        transport.reply(200, route.response)

        try await route.call(client)

        let request = transport.last
        #expect(request.httpMethod == route.method)
        #expect(request.url?.host() == "127.0.0.1")
        #expect(request.url?.port == 8765)
        #expect(request.target == route.target)
        #expect(request.bodyText == route.body)
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer tok-123")
        #expect(request.value(forHTTPHeaderField: "Accept") == "application/json")
        let contentType = request.value(forHTTPHeaderField: "Content-Type")
        #expect(contentType == (route.body == nil ? nil : "application/json"))
    }

    @Test func readsResponseValues() async throws {
        transport.reply(fixture: "sessions")
        let sessions = try await client.sessions(repo: nil, archived: false)
        #expect(sessions.map(\.title) == ["Validate contact form with zod", "Dark mode contrast"])

        transport.reply(200, #"{"launcher": "/tmp/x.command", "warning": "still running"}"#)
        #expect(try await client.openInClaudeCode("s1").warning == "still running")
    }

    @Test func pathComponentsAreEscaped() async throws {
        transport.reply(200, RouteCase.sessionJSON)
        _ = try await client.session("a b/c")
        #expect(transport.last.target == "/api/sessions/a%20b%2Fc")
    }

    @Test func usesTheGivenBaseURL() async throws {
        let remote = APIClient(
            token: "t", baseURL: URL(string: "https://mac.tailnet.ts.net")!, transport: transport)
        transport.reply(200, "[]")
        _ = try await remote.repos()
        #expect(transport.last.url?.absoluteString == "https://mac.tailnet.ts.net/api/repos")
        #expect(remote.baseURL.host() == "mac.tailnet.ts.net")
    }

    @Test func uploadsAttachmentsAsMultipart() async throws {
        transport.reply(
            201,
            #"{"id": "att1", "filename": "shot.png", "media_type": "image/png", "size": 3, "created_at": "2026-10-06T09:00:00Z"}"#
        )

        let attachment = try await client.uploadAttachment(
            filename: "shot.png", mediaType: "image/png", data: Data([1, 2, 3]))

        #expect(attachment.id == "att1")
        #expect(attachment.createdAt != nil)
        let request = transport.last
        #expect(request.target == "/api/attachments")
        #expect(request.httpMethod == "POST")
        let contentType = try #require(request.value(forHTTPHeaderField: "Content-Type"))
        #expect(contentType.hasPrefix("multipart/form-data; boundary=nest-"))
        let boundary = String(contentType.split(separator: "=").last!)
        let expected =
            Data(
                ("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"shot.png\"\r\n"
                    + "Content-Type: image/png\r\n\r\n").utf8) + Data([1, 2, 3])
            + Data("\r\n--\(boundary)--\r\n".utf8)
        #expect(request.httpBody == expected)
    }

    @Test func multipartFilenamesCannotBreakTheHeader() {
        let form = MultipartForm(
            fieldName: "file", filename: "a\"b\r\nc.txt", mediaType: "text/plain", data: Data(),
            boundary: "B")
        let text = String(decoding: form.body, as: UTF8.self)
        #expect(text.contains("filename=\"abc.txt\""))
        #expect(form.contentType == "multipart/form-data; boundary=B")
    }
}

@Suite struct AttachmentFileTests {
    func file(size: Int, named name: String = UUID().uuidString) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appending(path: name)
        FileManager.default.createFile(atPath: url.path, contents: nil)
        let handle = try FileHandle(forWritingTo: url)
        try handle.truncate(atOffset: UInt64(size))
        try handle.close()
        return url
    }

    @Test func readsAFileUpToTheDaemonsLimit() async throws {
        let small = try file(size: 3)
        defer { try? FileManager.default.removeItem(at: small) }
        #expect(try await AttachmentFile.read(small) == Data([0, 0, 0]))

        let largest = try file(size: AttachmentFile.maximumSize)
        defer { try? FileManager.default.removeItem(at: largest) }
        #expect(try await AttachmentFile.read(largest).count == 20 * 1024 * 1024)
    }

    @Test func refusesALargerFileBeforeReadingIt() async throws {
        let large = try file(size: AttachmentFile.maximumSize + 1)
        defer { try? FileManager.default.removeItem(at: large) }
        await #expect(throws: AttachmentFileError.tooLarge) {
            _ = try await AttachmentFile.read(large)
        }
        #expect(
            AttachmentFileError.tooLarge.localizedDescription
                == "attachments larger than 20 MB are not accepted")
    }

    /// A file that grows after its size was checked is still cut off at the limit: the
    /// read itself stops one byte past it and refuses (audit M-8).
    @Test func aFileThatGrewAfterTheCheckIsRefusedAfterReading() throws {
        let large = try file(size: AttachmentFile.maximumSize + 1)
        defer { try? FileManager.default.removeItem(at: large) }
        #expect(throws: AttachmentFileError.tooLarge) {
            _ = try AttachmentFile.readCapped(large)
        }
        let largest = try file(size: AttachmentFile.maximumSize)
        defer { try? FileManager.default.removeItem(at: largest) }
        #expect(try AttachmentFile.readCapped(largest).count == AttachmentFile.maximumSize)
    }

    @Test func anEmptyFileReadsEmpty() async throws {
        let empty = try file(size: 0)
        defer { try? FileManager.default.removeItem(at: empty) }
        #expect(try await AttachmentFile.read(empty).isEmpty)
    }

    @Test func aMissingFileFails() async {
        await #expect(throws: (any Error).self) {
            _ = try await AttachmentFile.read(URL(fileURLWithPath: "/no/such/file"))
        }
    }

    /// Folders and packages (an `.rtfd`, an app) are not files to attach; they say so
    /// rather than failing with a generic error (audit BUG-78).
    @Test func foldersAndPackagesAreRefusedClearly() async throws {
        let package = FileManager.default.temporaryDirectory.appending(path: "\(UUID()).rtfd")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: package) }
        for folder in [package, FileManager.default.temporaryDirectory] {
            await #expect(throws: AttachmentFileError.notAFile) {
                _ = try await AttachmentFile.read(folder)
            }
        }
        #expect(
            AttachmentFileError.notAFile.localizedDescription
                == "only files can be attached, not folders or packages")
    }

    /// A link is read as the file it points to, size check included (audit BUG-78).
    @Test func aLinkIsCheckedAsItsTarget() async throws {
        let large = try file(size: AttachmentFile.maximumSize + 1)
        let small = try file(size: 2)
        let links = [large, small].map { _ in
            FileManager.default.temporaryDirectory.appending(path: "\(UUID()).link")
        }
        try FileManager.default.createSymbolicLink(at: links[0], withDestinationURL: large)
        try FileManager.default.createSymbolicLink(at: links[1], withDestinationURL: small)
        defer {
            for url in [large, small] + links { try? FileManager.default.removeItem(at: url) }
        }
        await #expect(throws: AttachmentFileError.tooLarge) {
            _ = try await AttachmentFile.read(links[0])
        }
        #expect(try await AttachmentFile.read(links[1]) == Data([0, 0]))
    }

    @Test func uploadsWithTheFilesNameAndType() async throws {
        let api = FakeAPI()
        let text = try file(size: 3, named: "\(UUID()).txt")
        let other = try file(size: 1, named: "\(UUID()).zzunknown")
        defer {
            try? FileManager.default.removeItem(at: text)
            try? FileManager.default.removeItem(at: other)
        }
        let uploaded = try await AttachmentFile.upload(text, with: api)
        #expect(uploaded.filename == text.lastPathComponent)
        #expect(uploaded.mediaType == "text/plain")
        #expect(uploaded.size == 3)
        let unknown = try await AttachmentFile.upload(other, with: api)
        #expect(unknown.mediaType == "application/octet-stream")
    }
}

@Suite struct APIErrorTests {
    let transport = FakeTransport()
    var client: APIClient { APIClient(token: "t", transport: transport) }

    func failure(_ status: Int, _ body: String, headers: [String: String] = [:]) async -> APIError?
    {
        transport.reply(status, body, headers: headers)
        do {
            _ = try await client.repos()
            return nil
        } catch {
            return error as? APIError
        }
    }

    @Test func mapsStatusCodesWithTheDaemonsDetail() async {
        #expect(
            await failure(401, #"{"detail": "not authenticated"}"#)
                == .unauthorized("not authenticated"))
        #expect(
            await failure(404, #"{"detail": "unknown session"}"#) == .notFound("unknown session"))
        #expect(await failure(409, #"{"detail": "busy"}"#) == .conflict("busy"))
        #expect(
            await failure(
                409, #"{"detail": "changed", "code": "stale_file", "text": "t", "hash": "h"}"#)
                == .staleFile(text: "t", hash: "h"))
        #expect(
            await failure(409, #"{"detail": "changed", "code": "stale_file"}"#)
                == .conflict("changed"))
        #expect(
            await failure(
                409, #"{"detail": "Close it there first.", "code": "open_in_claude_code"}"#)
                == .openInClaudeCode("Close it there first."))
        #expect(
            await failure(409, #"{"detail": "Too late", "code": "message_taken"}"#)
                == .messageTaken("Too late"))
        #expect(APIError.messageTaken("Too late").isConflict)
        #expect(APIError.messageTaken("Too late").message == "Too late")
        #expect(
            await failure(409, #"{"detail": "other", "code": "something_else"}"#)
                == .conflict("other"))
        #expect(
            await failure(409, #"{"detail": "The branch moved.", "code": "head_changed"}"#)
                == .approveRefused("The branch moved.", reason: .headChanged))
        #expect(
            await failure(409, #"{"detail": "Wait for it.", "code": "background_running"}"#)
                == .approveRefused("Wait for it.", reason: .backgroundRunning))
        for code in [
            "nested_repository", "unsafe_branch", "unsafe_repo_config", "index_flags",
            "lfs_unsupported", "review_changed",
        ] {
            let error = await failure(409, #"{"detail": "No.", "code": "\#(code)"}"#)
            #expect(error == .approveRefused("No.", reason: ApproveRefusal(rawValue: code)!))
            #expect(error?.pushRemote == nil)
        }
        // A push address to confirm comes with where origin pushes now (I-008).
        let changed = await failure(
            409,
            #"{"detail": "Moved.", "code": "remote_changed", "remote_urls": ["git@new:r.git"], "confirmed_url": "git@old:r.git"}"#
        )
        let moved = PushRemote(urls: ["git@new:r.git"], confirmedURL: "git@old:r.git")
        #expect(changed == .approveRefused("Moved.", reason: .remoteChanged, remote: moved))
        #expect(changed?.pushRemote?.target == "git@new:r.git")
        let unconfirmed = await failure(
            409,
            #"{"detail": "Confirm.", "code": "remote_not_confirmed", "remote_urls": ["a", "b"], "confirmed_url": null}"#
        )
        #expect(unconfirmed?.pushRemote == PushRemote(urls: ["a", "b"]))
        #expect(unconfirmed?.pushRemote?.target == nil)
        let bare = await failure(409, #"{"detail": "None.", "code": "remote_not_confirmed"}"#)
        #expect(bare?.pushRemote == PushRemote(urls: []))
        #expect(APIError.notFound("x").pushRemote == nil)
        #expect(
            await failure(400, #"{"detail": "invalid or expired pairing code"}"#)
                == .invalidInput("invalid or expired pairing code"))
        #expect(await failure(413, #"{"detail": "too large"}"#) == .payloadTooLarge("too large"))
        #expect(
            await failure(424, #"{"detail": "VS Code is not installed"}"#)
                == .appNotInstalled("VS Code is not installed"))
        #expect(await failure(502, #"{"detail": "open failed"}"#) == .badGateway("open failed"))
        #expect(await failure(500, #"{"detail": "boom"}"#) == .server(status: 500, detail: "boom"))
    }

    @Test func gitFailuresCarryStepAndStderr() async {
        let error = await failure(
            502, #"{"detail": "git push failed: denied", "step": "push", "stderr": "denied\n"}"#)
        #expect(error == .gitFailed("git push failed: denied", step: "push", stderr: "denied\n"))
        let bare = await failure(502, #"{"detail": "git commit failed", "step": "commit"}"#)
        #expect(bare == .gitFailed("git commit failed", step: "commit", stderr: ""))
    }

    @Test func validationErrorsJoinTheirMessages() async {
        let error = await failure(
            422,
            #"{"detail": [{"loc": ["body", "prompt"], "msg": "Field required"}, {"loc": ["body"], "msg": "Extra inputs are not permitted"}]}"#
        )
        #expect(error == .invalidInput("Field required; Extra inputs are not permitted"))
    }

    @Test func rateLimitsReadRetryAfter() async {
        let error = await failure(
            429, #"{"detail": "too many failed pairing attempts"}"#, headers: ["retry-after": "60"])
        #expect(error == .rateLimited("too many failed pairing attempts", retryAfter: 60))
        #expect(await failure(429, "{}") == .rateLimited("client error", retryAfter: nil))
        // Without the header, the body's retry_after (the usage refresh sends both).
        #expect(
            await failure(429, #"{"detail": "too soon", "retry_after": 12}"#)
                == .rateLimited("too soon", retryAfter: 12))
    }

    @Test func bodiesWithoutDetailFallBackToTheStatusText() async {
        #expect(
            await failure(503, "<html>down</html>")
                == .server(status: 503, detail: "service unavailable"))
        #expect(await failure(404, #"{"detail": []}"#) == .notFound("not found"))
    }

    @Test func unreachableDaemonIsATransportError() async {
        transport.fail(.cannotConnectToHost)
        await #expect(throws: APIError.self) { _ = try await client.repos() }
    }

    @Test func unreadableResponsesAreDecodingErrors() async {
        transport.reply(200, #"{"status": 1}"#)
        do {
            _ = try await client.repos()
            Issue.record("expected a decoding error")
        } catch let error as APIError {
            guard case .decoding = error else {
                Issue.record("got \(error)")
                return
            }
        } catch {
            Issue.record("got \(error)")
        }
    }

    @Test func everyErrorHasAMessage() {
        let errors: [APIError] = [
            .unauthorized("a"), .notFound("a"), .conflict("a"),
            .openInClaudeCode("a"), .invalidInput("a"),
            .payloadTooLarge("a"), .rateLimited("a", retryAfter: nil), .appNotInstalled("a"),
            .gitFailed("a", step: "s", stderr: ""), .badGateway("a"),
            .server(status: 500, detail: "a"),
            .transport("a"), .decoding("a"), .approveRefused("a", reason: .headChanged),
        ]
        #expect(errors.map(\.message) == Array(repeating: "a", count: errors.count))
        #expect(
            APIError.staleFile(text: "t", hash: "h").message
                == "The file changed since you opened it.")
    }

    /// Every 409 means the chat changed since the app last read it.
    @Test func conflictsAreTold() {
        let conflicts: [APIError] = [
            .conflict("a"), .openInClaudeCode("a"),
            .approveRefused("a", reason: .headChanged),
        ]
        #expect(conflicts.allSatisfy { $0.isConflict })
        #expect(!APIError.server(status: 500, detail: "a").isConflict)
        #expect(!APIError.gitFailed("a", step: "push", stderr: "").isConflict)
    }

    @Test func aMovedBranchSaysWhatToDo() {
        #expect(
            ApproveRefusal.headChanged.hint
                == "The branch moved since you looked. Check the changes again."
        )
        #expect(
            ApproveRefusal.reviewChanged.hint
                == "The changes were read again. Check them before approving.")
        #expect(ApproveRefusal.backgroundRunning.hint == nil)
        #expect(ApproveRefusal.indexFlags.hint == nil)
        #expect(ApproveRefusal.lfsUnsupported.hint == nil)
    }
}
