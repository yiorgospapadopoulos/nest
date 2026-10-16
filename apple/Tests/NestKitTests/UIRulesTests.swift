import Foundation
import Testing

@testable import NestKit

/// The shared UI rules both clients follow (IMP-10), as `design/ui-rules.json` states
/// them; the iPhone has the same test against its own tables.
struct UIRules: Decodable {
    struct Case: Decodable {
        var state: SessionState
        var pending: [ApprovalKind]
        var stuck: Bool?
        var pinned: Bool?
        var label: String
        var tone: String
        var group: String
    }

    struct Status: Decodable {
        var cases: [Case]
    }

    struct Group: Decodable {
        var id: String
        var label: String
    }

    struct ChecksFailed: Decodable {
        var prState: String
        var checksState: String
        var notInStates: [SessionState]
        var notWithPending: [ApprovalKind]
        var notArchived: Bool

        enum CodingKeys: String, CodingKey {
            case prState = "pr_state"
            case checksState = "checks_state"
            case notInStates = "not_in_states"
            case notWithPending = "not_with_pending"
            case notArchived = "not_archived"
        }
    }

    struct Badge: Decodable {
        var counts: [String]
        var checksFailed: ChecksFailed

        enum CodingKeys: String, CodingKey {
            case counts
            case checksFailed = "checks_failed"
        }
    }

    struct NeedsYou: Decodable {
        var order: [String]
        var approvals: String
        var checksFailed: String
        var stuck: String

        enum CodingKeys: String, CodingKey {
            case order, approvals, stuck
            case checksFailed = "checks_failed"
        }
    }

    struct NotificationKind: Decodable {
        var kind: NoticeKind
        var label: String
    }

    var status: Status
    var groups: [Group]
    var badge: Badge
    var needsYou: NeedsYou
    var notificationKinds: [NotificationKind]

    enum CodingKeys: String, CodingKey {
        case status, groups, badge
        case needsYou = "needs_you"
        case notificationKinds = "notification_kinds"
    }

    /// `design/ui-rules.json`, found from this file's place in the repository.
    static func load(from file: String = #filePath) throws -> UIRules {
        let url = URL(fileURLWithPath: file)
            .deletingLastPathComponent()  // NestKitTests
            .deletingLastPathComponent()  // Tests
            .deletingLastPathComponent()  // apple
            .deletingLastPathComponent()  // the repository
            .appending(path: "design/ui-rules.json")
        return try JSONDecoder().decode(UIRules.self, from: Data(contentsOf: url))
    }
}

@MainActor
@Suite struct UIRulesTests {
    let rules: UIRules
    let api = FakeAPI()
    let approvals: ApprovalsStore
    let sessions: SessionsStore

    init() throws {
        rules = try UIRules.load()
        approvals = ApprovalsStore(api: api)
        sessions = SessionsStore(api: api, approvals: approvals)
    }

    /// The table's name for a session's tone; idle is a done tone on an idle chat, which
    /// the Mac draws as a filled done dot.
    func toneName(_ session: Session) -> String {
        if session.state == .idle && sessions.tone(of: session) == .done {
            return "idle"
        }
        switch sessions.tone(of: session) {
        case .running: return "running"
        case .waiting: return "waiting"
        case .review: return "review"
        case .failed: return "failed"
        case .interrupted: return "interrupted"
        case .done: return "done"
        }
    }

    static let groupIDs: [SessionGroupKind: String] = [
        .pinned: "pinned", .needsYou: "needs_you", .running: "running", .idle: "idle",
        .done: "done",
    ]

    func approval(_ kind: ApprovalKind, for session: String, index: Int) -> Approval {
        var approval = Fixture.approval("ap-perm")
        approval.id = "\(session)-\(index)"
        approval.sessionID = session
        approval.kind = kind
        return approval
    }

    @Test func statusLabelsTonesAndGroupsMatch() throws {
        #expect(!rules.status.cases.isEmpty)
        for (index, rule) in rules.status.cases.enumerated() {
            let id = "case-\(index)"
            var session = Fixture.session(id, state: rule.state, pinned: rule.pinned ?? false)
            if rule.stuck == true {
                session.stuck = StuckFlag(
                    reason: .silent, since: Date(timeIntervalSince1970: 0), details: "Quiet")
            }
            sessions.insert(session)
            for (number, kind) in rule.pending.enumerated() {
                approvals.apply(.approvalCreated(approval(kind, for: id, index: number)))
            }
            let context = "\(rule.state) \(rule.pending)"
            #expect(sessions.statusLabel(of: session) == rule.label, "\(context)")
            #expect(toneName(session) == rule.tone, "\(context)")
            #expect(
                Self.groupIDs[sessions.group(of: session)] == rule.group, "\(context)")
        }
    }

    @Test func groupsAreListedInTheSameOrder() {
        let listed = SessionGroupKind.allCases.filter { $0 != .archived }
        #expect(listed.map { Self.groupIDs[$0] } == rules.groups.map(\.id))
        #expect(listed.map(\.title) == rules.groups.map(\.label))
    }

    @Test func notificationKindsMatchTheSettingsToggles() {
        let toggles = NotificationPreferences.toggles.filter { $0.title != "Sound" }
        #expect(toggles.map(\.title) == rules.notificationKinds.map(\.label))
        for (toggle, rule) in zip(toggles, rules.notificationKinds) {
            var preferences = NotificationPreferences()
            for other in toggles {
                preferences[keyPath: other.path] = false
            }
            preferences[keyPath: toggle.path] = true
            let wanted = rules.notificationKinds.map(\.kind).filter(preferences.wants)
            #expect(wanted == [rule.kind], "\(rule.label)")
        }
    }

    @Test func needsYouListsTheSameKindsInTheSameOrder() {
        #expect(NeedsYouSection.allCases.map(\.rawValue) == rules.needsYou.order)
        #expect(rules.badge.counts == rules.needsYou.order)
        #expect(rules.needsYou.approvals == "oldest_first")
        #expect(rules.needsYou.checksFailed == "oldest_check_change_first")
        #expect(rules.needsYou.stuck == "longest_stuck_first")
    }

    static func pr(changed: String, state: String = "open", checks: String = "failure")
        -> PullRequest
    {
        Fixture.decode(
            PullRequest.self,
            json: """
                {"number": 1, "url": "https://github.com/me/r/pull/1", "title": "T",
                 "state": "\(state)",
                 "checks": {"state": "\(checks)", "passed": 0, "failed": 1, "pending": 0,
                            "items": [{"name": "test", "state": "failure", "url": null}]},
                 "mergeable": null, "merge_state": null, "review_decision": null,
                 "head_sha": null, "created_at": null,
                 "changed_at": "\(changed)", "updated_at": "\(changed)"}
                """)
    }

    /// Who counts as failed checks, in which order, and what the badge adds up.
    @Test func checksFailedStuckAndTheBadgeFollowTheRules() {
        let rule = rules.badge.checksFailed
        #expect(rule.prState == PRState.open.rawValue)
        #expect(rule.checksState == ChecksState.failure.rawValue)
        #expect(rule.notArchived)
        func failing(_ id: String, _ state: SessionState = .idle, changed: String) -> Session {
            var session = Fixture.session(id, state: state)
            session.pr = Self.pr(changed: changed)
            return session
        }
        let late = failing("late", changed: "2026-10-06T10:00:00Z")
        let early = failing("early", .failed, changed: "2026-10-06T09:00:00Z")
        for session in [late, early] {
            sessions.insert(session)
        }
        for (index, state) in rule.notInStates.enumerated() {
            sessions.insert(failing("busy-\(index)", state, changed: "2026-10-06T08:00:00Z"))
        }
        var archived = failing("archived", changed: "2026-10-06T08:00:00Z")
        archived.archivedAt = Date(timeIntervalSince1970: 1)
        sessions.insert(archived)
        var merged = failing("merged", changed: "2026-10-06T08:00:00Z")
        merged.pr = Self.pr(changed: "2026-10-06T08:00:00Z", state: "merged")
        sessions.insert(merged)
        var green = failing("green", changed: "2026-10-06T08:00:00Z")
        green.pr = Self.pr(changed: "2026-10-06T08:00:00Z", checks: "success")
        sessions.insert(green)
        let reviewing = failing("reviewing", changed: "2026-10-06T08:00:00Z")
        sessions.insert(reviewing)
        for (index, kind) in rule.notWithPending.enumerated() {
            approvals.apply(.approvalCreated(approval(kind, for: "reviewing", index: index)))
        }

        #expect(sessions.checksFailed(in: "cv-page").map(\.id) == ["early", "late"])

        var stuckLong = Fixture.session("stuck-long", state: .running)
        stuckLong.stuck = StuckFlag(
            reason: .silent, since: Date(timeIntervalSince1970: 10), details: "Quiet")
        var stuckNew = stuckLong
        stuckNew.id = "stuck-new"
        stuckNew.stuck?.since = Date(timeIntervalSince1970: 20)
        sessions.insert(stuckNew)
        sessions.insert(stuckLong)
        #expect(sessions.stuck(in: "cv-page").map(\.id) == ["stuck-long", "stuck-new"])

        // Approvals, failed checks and stuck chats add up.
        #expect(sessions.attention(of: "cv-page") == rule.notWithPending.count + 2 + 2)
    }

    /// Failed checks count in every state the rule does not exclude, so a table that
    /// excludes fewer states fails here too, not only one that excludes more (audit W-5).
    @Test func checksFailedCountInEveryStateTheRuleAllows() {
        let states: [SessionState] = [
            .starting, .running, .waiting, .idle, .interrupted, .failed, .closed,
        ]
        for state in states {
            var session = Fixture.session("s-\(state.rawValue)", state: state)
            session.pr = Self.pr(changed: "2026-10-06T08:00:00Z")
            sessions.insert(session)
        }
        let counted = Set(sessions.checksFailed(in: "cv-page").map(\.state))
        #expect(counted == Set(states).subtracting(rules.badge.checksFailed.notInStates))
        #expect(!counted.isEmpty)
    }

    @Test func approvalsStayOldestFirst() async throws {
        let first = approval(.permission, for: "s1", index: 1)
        var second = approval(.question, for: "s1", index: 2)
        second.createdAt = first.createdAt.addingTimeInterval(60)
        api.set { $0.approvals = [first] }
        try await approvals.load()
        approvals.apply(.approvalCreated(second))
        #expect(approvals.pending(repo: first.repo).map(\.id) == [first.id, second.id])
    }
}
