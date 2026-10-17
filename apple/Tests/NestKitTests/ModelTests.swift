import Foundation
import Testing

@testable import NestKit

@Suite struct SessionDecodingTests {
    @Test func decodesASessionDetailWithTasksAndAgents() throws {
        let session = Fixture.sessionDetail

        #expect(session.id == "5b8f3c2a9d1e4f60a7b8c9d0e1f2a3b4")
        #expect(session.repo == "cv-page")
        #expect(session.mode == .worktree)
        #expect(session.state == .waiting)
        #expect(session.effort == .medium)
        #expect(session.permissionMode == .acceptEdits)
        #expect(session.branch == "agent/contact-zod-3f2a")
        #expect(session.pinned)
        #expect(!session.isArchived)
        #expect(session.allowedTools == ["Bash"])
        #expect(session.prURL == nil)
        #expect(abs(session.createdAt.timeIntervalSince1970 - 1_791_277_950.482113) < 0.000_01)
        #expect(session.updatedAt == Date(timeIntervalSince1970: 1_791_278_042))
        let tasks = try #require(session.tasks)
        #expect(tasks.map(\.status) == [.completed, .inProgress, .pending])
        #expect(tasks[0].activeForm == "Adding zod schema")
        let agents = try #require(session.agents)
        #expect(agents.map(\.isMain) == [true, false])
        #expect(agents[0].status == .running)
        #expect(agents[0].steps.map(\.tool) == ["Read", "Edit"])
        #expect(agents[1].finishedAt == Date(timeIntervalSince1970: 1_791_277_985.5))
    }

    @Test func decodesListEntriesWithoutTasksAndWithOffsetDates() {
        let sessions = Fixture.sessions

        #expect(sessions[1].mode == .inPlace)
        #expect(sessions[1].model == nil)
        #expect(sessions[1].effort == nil)
        #expect(sessions[1].prURL == "https://github.com/example/cv-page/pull/14")
        #expect(sessions[1].tasks == nil)
        #expect(sessions[1].updatedAt == Date(timeIntervalSince1970: 1_791_223_200.25))
        #expect(Fixture.archivedSessions[0].isArchived)
    }

    @Test func unknownEnumValuesDecodeAsUnknown() {
        let json = Fixture.text("session_detail")
            .replacingOccurrences(of: "\"waiting\"", with: "\"hibernating\"")
            .replacingOccurrences(of: "\"acceptEdits\"", with: "\"yolo\"")
            .replacingOccurrences(of: "\"in_progress\"", with: "\"blocked\"")
        let session = Fixture.decode(Session.self, json: json)

        #expect(session.state == .unknown)
        #expect(session.permissionMode == .unknown)
        #expect(session.tasks?[1].status == .unknown)
    }

    @Test func inFlightStatesAreTheWorkingOnes() {
        let inFlight = [SessionState.starting, .running, .waiting]
        let settled = [SessionState.idle, .interrupted, .failed, .closed, .unknown]
        #expect(inFlight.map(\.isInFlight) == [true, true, true])
        #expect(settled.filter(\.isInFlight).isEmpty)
    }

    @Test func permissionModesHaveComposerLabels() {
        #expect(
            PermissionMode.selectable.map(\.label) == ["Ask", "Accept edits", "Plan", "Bypass"])
        #expect(PermissionMode.unknown.label == "Unknown")
        #expect(PermissionMode.auto.label == "Auto")
        #expect(PermissionMode.options(supportsAuto: false) == PermissionMode.selectable)
        #expect(PermissionMode.options(supportsAuto: true) == PermissionMode.selectable + [.auto])
        #expect(PermissionMode.label(nil) == "Claude Code default")
        #expect(PermissionMode.label(.plan) == "Plan")
        #expect(Effort.selectable.map(\.rawValue) == ["low", "medium", "high", "xhigh", "max"])
    }

    @Test func rejectsADateThatIsNotISO8601() {
        let json = Fixture.text("session_detail")
            .replacingOccurrences(of: "2026-10-06T09:14:02Z", with: "yesterday")
        #expect(throws: DecodingError.self) {
            try NestJSON.decoder.decode(Session.self, from: Data(json.utf8))
        }
    }

    @Test func readsThePixieAChatBelongsTo() throws {
        #expect(Fixture.sessions[0].pixieID == nil)
        let json = Fixture.json(Fixture.sessions[0]).dropLast()
        let chat = Fixture.decode(Session.self, json: json + #","pixie_id":"p1"}"#)
        #expect(chat.pixieID == "p1")
    }

    @Test func encodesDatesWithFractionalSeconds() throws {
        var session = Fixture.sessions[0]
        session.archivedAt = Date(timeIntervalSince1970: 1_791_278_350.5)
        let object = try JSONSerialization.jsonObject(with: NestJSON.encoder.encode(session))
        let dictionary = try #require(object as? [String: Any])
        #expect(dictionary["archived_at"] as? String == "2026-10-06T09:19:10.500Z")
        #expect(dictionary["permission_mode"] as? String == "acceptEdits")
    }
}

@Suite struct RepoAndAccountDecodingTests {
    @Test func decodesReposWithWorktreeConfig() {
        let repos = Fixture.repos
        #expect(repos.map(\.id) == ["cv-page", "llm-hunter"])
        #expect(
            repos[0].worktree
                == WorktreeConfig(isDefault: true, link: [".env.local"], setup: ["npm ci"]))
        #expect(repos[1].defaultBranch == "develop")
        #expect(repos[1].worktree.isDefault == false)
        #expect(repos[1].worktree.setupTimeoutSeconds == 300)
    }

    /// B36: a pixie sprite in a pixie colour, or the initials in the default colour.
    @Test func decodesTheProjectIcon() throws {
        let repos = Fixture.repos
        #expect(repos[0].projectIcon == ProjectIcon())
        #expect(repos[1].projectIcon == ProjectIcon(mascot: .frog, color: "#3DDC84"))
        // Older daemons send neither key.
        #expect(Fixture.plainRepo.projectIcon == ProjectIcon())
        // A sprite this app does not know shows the initials.
        let json = #"""
            {"name": "a", "path": "/a", "icon": "dragon", "icon_color": "#000000",
             "worktree": {"link": [], "setup": [], "setup_timeout_seconds": 900}}
            """#
        let repo = try NestJSON.decoder.decode(Repo.self, from: Data(json.utf8))
        #expect(repo.projectIcon == ProjectIcon(mascot: nil, color: "#000000"))
    }

    @Test func aRepoWithoutItsOwnChoiceFollowsTheSharedDefault() throws {
        let json = #"{"link": [], "setup": [], "setup_timeout_seconds": 900, "default": null}"#
        let config = try NestJSON.decoder.decode(WorktreeConfig.self, from: Data(json.utf8))
        #expect(config.isDefault == nil)
    }

    @Test func decodesConnectors() {
        let connectors = Fixture.connectors
        #expect(connectors.map(\.id) == ["claude.ai Gmail", "plugin:engineering:github", "serena"])
        #expect(connectors.map(\.group) == [.claudeAI, .plugin, .local])
        #expect(connectors.map(\.manageHint) == [.claudeAI, .claudeCode, .claudeCode])
        #expect(connectors[2].error == "spawn ENOENT")
    }

    @Test func decodesUsage() {
        let period = Fixture.usagePeriod
        #expect(period.tokens.cacheReadInputTokens == 12_100_000)
        #expect(period.tokens.cacheCreationInputTokens == 2_800_000)

        let limits = Fixture.usageLimits
        #expect(limits.fiveHour?.utilization == 0.3)
        #expect(limits.fiveHour?.updatedAt == Date(timeIntervalSince1970: 1_791_295_200.5))
        #expect(limits.sevenDay == nil)
    }

    @Test func decodesDevicesAndPairingCodes() {
        let devices = Fixture.decode([Device].self, "devices")
        #expect(devices.map(\.isLocal) == [true, false])
        #expect(devices[1].revokedAt != nil)
        let code = Fixture.decode(
            PairingCode.self, json: #"{"code": "4F7K-9QX2", "expires_at": "2026-10-06T09:05:00Z"}"#)
        #expect(code.code == "4F7K-9QX2")
    }

    @Test func calendarDaysParseCompareAndPrint() {
        let day = Fixture.decode(CalendarDay.self, json: #""2026-03-07""#)
        #expect(day == CalendarDay(year: 2026, month: 3, day: 7))
        #expect(day.description == "2026-03-07")
        #expect(CalendarDay(year: 2026, month: 11, day: 12).description == "2026-11-12")
        #expect(day < CalendarDay(year: 2026, month: 3, day: 8))
        #expect(throws: DecodingError.self) {
            try NestJSON.decoder.decode(CalendarDay.self, from: Data(#""March 7""#.utf8))
        }
    }
}

@Suite struct ApprovalDecodingTests {
    @Test func permissionPayloadIsTyped() throws {
        let approval = Fixture.approval("ap-perm")
        let permission = try #require(approval.permission)
        #expect(permission.tool == "Bash")
        #expect(permission.input["command"]?.stringValue == "npm install zod")
        #expect(permission.title == "Allow Bash: npm install zod?")
        #expect(approval.question == nil)
        #expect(approval.review == nil)
    }

    @Test func permissionPayloadCarriesTheEnginesReason() throws {
        var approval = Fixture.approval("ap-perm")
        #expect(approval.permission?.reason == nil)
        approval.payload = Fixture.decode(
            JSONValue.self,
            json:
                #"{"tool": "Bash", "input": {"command": "rm -r build"}, "title": null, "reason": "No allow rule matches rm"}"#
        )
        #expect(approval.permission?.reason == "No allow rule matches rm")
    }

    /// "Always allow" names exactly what it allows: the daemon's rule (IMP-06, B59), else,
    /// for older events and other providers, the tool.
    @Test func permissionPayloadCarriesTheSuggestedRule() throws {
        var approval = Fixture.approval("ap-perm")
        let plain = try #require(approval.permission)
        #expect(plain.alwaysRule == nil)
        #expect(plain.alwaysAllowTitle == "Always allow Bash")
        #expect(plain.alwaysAllowHelp == "Allow Bash without asking again in this chat")

        approval.payload = Fixture.decode(
            JSONValue.self,
            json: #"{"tool": "Bash", "input": {}, "always_rule": "Bash(npm test:*)"}"#)
        let ruled = try #require(approval.permission)
        #expect(ruled.alwaysRule == "Bash(npm test:*)")
        #expect(ruled.alwaysAllowTitle == "Always allow Bash(npm test:*)")
        #expect(ruled.alwaysAllowHelp == "Allow Bash(npm test:*) without asking again")

        approval.payload = Fixture.decode(
            JSONValue.self,
            json: #"{"tool": "Bash", "input": {}, "always_rule": "Bash(rm -rf build)"}"#)
        #expect(approval.permission?.alwaysAllowTitle == "Always allow Bash(rm -rf build)")

        approval.payload = Fixture.decode(
            JSONValue.self, json: #"{"tool": "Bash", "input": {}, "always_rule": "  "}"#)
        #expect(approval.permission?.alwaysAllowTitle == "Always allow Bash")
        #expect(approval.permission?.suggestedRule == nil)
    }

    @Test func questionPayloadKeepsRecommendedFlags() throws {
        let approval = Fixture.approval("ap-question")
        let question = try #require(approval.question)
        #expect(question.toolUseID == "toolu_q1")
        #expect(question.questions.map(\.multiSelect) == [false, true])
        #expect(question.questions[0].options.map(\.recommended) == [false, true])
        #expect(question.questions[1].header == nil)
        #expect(approval.permission == nil)
    }

    @Test func reviewPayloadHasStatsAndPaths() throws {
        let approval = Fixture.approval("ap-review")
        let review = try #require(approval.review)
        #expect(review.files == 3)
        #expect(review.additions == 48)
        #expect(review.deletions == 19)
        #expect(review.paths.count == 3)
        #expect(review.summary?.hasPrefix("Raised contrast") == true)
        #expect(approval.status == .pending)
        #expect(approval.resolution == nil)
    }

    @Test func malformedPayloadReadsAsNil() {
        var approval = Fixture.approval("ap-perm")
        approval.payload = .object(["tool": .number(3)])
        #expect(approval.permission == nil)
    }
}

@Suite struct DiffDecodingTests {
    @Test func decodesFilesHunksAndLines() {
        let diff = Fixture.diff
        #expect(diff.stats == DiffStats(files: 2, additions: 3, deletions: 1))
        let file = diff.files[0]
        #expect(file.id == "app/globals.css")
        #expect(file.status == .modified)
        #expect(file.hunks[0].header == ":root {")
        #expect(file.hunks[0].oldStart == 10)
        #expect(file.hunks[0].newLines == 4)
        #expect(file.hunks[0].lines.map(\.kind) == [.context, .delete, .add, .add])
        #expect(file.hunks[0].lines[1].newLine == nil)
        #expect(file.hunks[0].lines[2].oldLine == nil)
        #expect(diff.files[1].oldPath == "public/old-logo.png")
        #expect(diff.files[1].status == .renamed)
        #expect(diff.files[1].binary)
        // The fixture is an older daemon's, without the nested repository flag.
        #expect(!file.isNestedRepository)
    }

    @Test func aNestedRepositoryIsFlagged() {
        let file = Fixture.decode(
            FileDiff.self,
            json: #"""
                {"path": "vendor/lib", "old_path": null, "status": "added", "additions": 0,
                 "deletions": 0, "binary": false, "truncated": false, "hunks": [],
                 "nested_repository": true}
                """#)
        #expect(file.isNestedRepository)
        #expect(FileDiff.nestedRepositoryNote == "Nested repository, not committed")
    }

    @Test func decodesWhatApprovePublishes() {
        let diff = Fixture.diff
        #expect(
            diff.head
                == ReviewHead(
                    commit: "2222222222222222222222222222222222222222",
                    branch: "agent/dark-mode-1a2b3c"))
        #expect(diff.target(pushes: true) == "Pushes to agent/dark-mode-1a2b3c")
        // An approve that only commits says it does not push (B56).
        #expect(diff.target(pushes: false) == "Commits to agent/dark-mode-1a2b3c, not pushed")
        #expect(diff.fingerprint == "fp-1")
    }

    @Test func aDiffFromAnOlderDaemonHasNoHead() {
        let empty = #""stats": {"files": 0, "additions": 0, "deletions": 0}, "files": []"#
        let diff = Fixture.decode(SessionDiff.self, json: #"{"base": null, \#(empty)}"#)
        #expect(diff.head == nil)
        #expect(diff.fingerprint == nil)
        #expect(diff.target(pushes: true) == nil)
        // A detached HEAD names no branch.
        let head = #""head": {"commit": "c", "branch": null}"#
        let detached = Fixture.decode(
            SessionDiff.self, json: #"{"base": null, \#(head), \#(empty)}"#)
        #expect(detached.head == ReviewHead(commit: "c", branch: nil))
        #expect(detached.target(pushes: false) == nil)
    }
}

@Suite struct JSONValueTests {
    @Test func decodesEveryKindOfValue() throws {
        let value = Fixture.decode(
            JSONValue.self,
            json: #"{"a": null, "b": true, "c": 2.5, "d": "x", "e": [1, "y"], "f": {"g": false}}"#)

        #expect(value["a"] == .null)
        #expect(value["b"]?.boolValue == true)
        #expect(value["c"]?.numberValue == 2.5)
        #expect(value["d"]?.stringValue == "x")
        #expect(value["e"]?.arrayValue == [.number(1), .string("y")])
        #expect(value["missing"] == nil)
    }

    @Test func accessorsOfTheWrongKindAreNil() {
        let value = JSONValue.string("x")
        #expect(value["key"] == nil)
        #expect(value.boolValue == nil)
        #expect(value.numberValue == nil)
        #expect(value.arrayValue == nil)
        #expect(JSONValue.null.stringValue == nil)
    }

    @Test func roundTripsThroughJSON() throws {
        let value = JSONValue.object([
            "a": .null, "b": .bool(true), "c": .number(1), "d": .string("x"),
            "e": .array([.number(2)]),
        ])
        let data = try NestJSON.encoder.encode(value)
        #expect(try NestJSON.decoder.decode(JSONValue.self, from: data) == value)
    }

    @Test func decodesIntoTypedModels() throws {
        let value = JSONValue.object(["launcher": .string("/tmp/a.command"), "warning": .null])
        #expect(
            try value.decode(ClaudeCodeLaunch.self)
                == ClaudeCodeLaunch(launcher: "/tmp/a.command", warning: nil))
        #expect(throws: DecodingError.self) { try JSONValue.null.decode(ClaudeCodeLaunch.self) }
    }
}
