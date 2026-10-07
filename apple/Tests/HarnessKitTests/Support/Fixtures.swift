import Foundation

@testable import HarnessKit

/// JSON shaped like real daemon responses, from `Fixtures/`.
enum Fixture {
    static func data(_ name: String) -> Data {
        let url = Bundle.module.url(forResource: "Fixtures/\(name)", withExtension: "json")!
        return try! Data(contentsOf: url)
    }

    static func text(_ name: String) -> String {
        String(decoding: data(name), as: UTF8.self)
    }

    static func decode<T: Decodable>(_ type: T.Type, _ name: String) -> T {
        try! HarnessJSON.decoder.decode(type, from: data(name))
    }

    static func decode<T: Decodable>(_ type: T.Type, json: String) -> T {
        try! HarnessJSON.decoder.decode(type, from: Data(json.utf8))
    }

    static var sessionDetail: Session { decode(Session.self, "session_detail") }
    static var sessions: [Session] { decode([Session].self, "sessions") }
    static var archivedSessions: [Session] { decode([Session].self, "sessions_archived") }
    static var repos: [Repo] { decode([Repo].self, "repos") }
    static var plainRepo: Repo { decode(Repo.self, "repo_plain") }
    static var approvals: [Approval] { decode([Approval].self, "approvals") }
    static var events: [Event] { decode([Event].self, "session_events") }
    static var diff: SessionDiff { decode(SessionDiff.self, "diff") }
    static var connectors: [Connector] { decode([Connector].self, "connectors") }
    static var usageMonth: UsageMonth { decode(UsageMonth.self, "usage_month") }
    static var usageLimits: UsageLimits { decode(UsageLimits.self, "usage_limits") }
    static var models: [ModelInfo] { decode(ModelList.self, "models").models }
    static var claudeChats: [ClaudeChat] { decode([ClaudeChat].self, "claude_chats") }
    static var claudeChatEvents: [Event] { decode([Event].self, "claude_chat_events") }

    /// A Claude Code chat with changes applied.
    static func claudeChat(
        _ id: String, repo: String = "todo-ui", title: String = "A Claude Code chat",
        lastActivity: Double = 1_000, automated: Bool = false, archived: Bool = false
    ) -> ClaudeChat {
        ClaudeChat(
            id: id, repo: repo, title: title, cwd: "/repo/\(repo)",
            createdAt: Date(timeIntervalSince1970: 0),
            lastActivityAt: Date(timeIntervalSince1970: lastActivity), messageCount: 2,
            automated: automated, archived: archived)
    }

    static func approval(_ id: String) -> Approval {
        approvals.first { $0.id == id }!
    }

    /// A session from the list fixture with changes applied.
    static func session(
        _ id: String = "s1", repo: String = "todo-ui", title: String = "A chat",
        state: SessionState = .idle, pinned: Bool = false, archived: Bool = false,
        updatedAt: Date = Date(timeIntervalSince1970: 1_000)
    ) -> Session {
        var session = sessions[0]
        session.id = id
        session.repo = repo
        session.title = title
        session.state = state
        session.pinned = pinned
        session.archivedAt = archived ? Date(timeIntervalSince1970: 2_000) : nil
        session.updatedAt = updatedAt
        session.tasks = nil
        session.agents = nil
        return session
    }

    /// An event built from a JSON payload.
    static func event(
        _ type: String, _ payload: String, id: Int? = 1, session: String? = "s1",
        ts: String = "2026-10-06T09:00:00Z"
    ) -> Event {
        let sessionJSON = session.map { "\"\($0)\"" } ?? "null"
        let idJSON = id.map(String.init) ?? "null"
        return decode(
            Event.self,
            json: """
                {"id": \(idJSON), "type": "\(type)", "ts": "\(ts)",
                 "session_id": \(sessionJSON), "payload": \(payload)}
                """)
    }

    /// A date from an ISO 8601 timestamp such as an event's `ts`.
    static func date(_ text: String) -> Date {
        try! Date(text, strategy: .iso8601)
    }

    static func json(_ value: some Encodable) -> String {
        String(decoding: try! HarnessJSON.encoder.encode(value), as: UTF8.self)
    }
}
