import Foundation

@testable import NestKit

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
        try! NestJSON.decoder.decode(type, from: data(name))
    }

    static func decode<T: Decodable>(_ type: T.Type, json: String) -> T {
        try! NestJSON.decoder.decode(type, from: Data(json.utf8))
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
    static var usagePeriod: UsagePeriod { decode(UsagePeriod.self, "usage_period") }
    static var usageLimits: UsageLimits { decode(UsageLimits.self, "usage_limits") }
    static var models: [ModelInfo] { decode(ModelList.self, "models").models }
    static var claudeChats: [ClaudeChat] { decode([ClaudeChat].self, "claude_chats") }
    static var claudeChatEvents: [Event] { decode([Event].self, "claude_chat_events") }

    /// A Claude Code chat with changes applied.
    static func claudeChat(
        _ id: String, repo: String = "cv-page", title: String = "A Claude Code chat",
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
        _ id: String = "s1", repo: String = "cv-page", title: String = "A chat",
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
        String(decoding: try! NestJSON.encoder.encode(value), as: UTF8.self)
    }
}

// MARK: Artifacts (B79)

extension Fixture {
    /// An artifact as the daemon lists it.
    static func artifactJSON(
        id: String = "a1", title: String = "Options compared", kind: String = "markdown",
        repo: String = "cv-page", session: String? = "s1", chatTitle: String? = "Pick a queue",
        chatDeleted: Bool = false, pixie: String? = nil, pixieName: String? = nil,
        updated: String = "2026-10-17T09:42:10+00:00", latest: Int = 3, seen: Bool = false
    ) -> String {
        func text(_ value: String?) -> String { value.map { "\"\($0)\"" } ?? "null" }
        return """
            {"id": "\(id)", "title": "\(title)", "kind": "\(kind)", "repo": "\(repo)",
             "session_id": \(text(session)), "chat_title": \(text(chatTitle)),
             "chat_deleted": \(chatDeleted), "pixie_id": \(text(pixie)),
             "pixie_name": \(text(pixieName)), "created_at": "2026-10-17T09:30:00+00:00",
             "updated_at": "\(updated)", "latest_version": \(latest),
             "version_count": \(latest), "seen": \(seen)}
            """
    }

    static func artifact(
        id: String = "a1", title: String = "Options compared", kind: String = "markdown",
        repo: String = "cv-page", session: String? = "s1", chatTitle: String? = "Pick a queue",
        chatDeleted: Bool = false, pixie: String? = nil, pixieName: String? = nil,
        updated: String = "2026-10-17T09:42:10+00:00", latest: Int = 3, seen: Bool = false
    ) -> Artifact {
        decode(
            Artifact.self,
            json: artifactJSON(
                id: id, title: title, kind: kind, repo: repo, session: session,
                chatTitle: chatTitle, chatDeleted: chatDeleted, pixie: pixie,
                pixieName: pixieName, updated: updated, latest: latest, seen: seen))
    }

    /// The artifact with one version entry per version.
    static func detail(_ artifact: Artifact) -> ArtifactDetail {
        let versions = (1...artifact.latestVersion).map { version in
            """
            {"version": \(version), "title": "\(artifact.title)", "size": 10,
             "created_at": "2026-10-17T09:30:00+00:00"}
            """
        }
        let json = artifactJSON(
            id: artifact.id, title: artifact.title, kind: artifact.kind.rawValue,
            repo: artifact.repo, session: artifact.sessionID, chatTitle: artifact.chatTitle,
            chatDeleted: artifact.chatDeleted, pixie: artifact.pixieID,
            pixieName: artifact.pixieName, latest: artifact.latestVersion, seen: artifact.seen)
        return decode(
            ArtifactDetail.self,
            json: String(json.dropLast())
                + #", "versions": [\#(versions.joined(separator: ","))]}"#)
    }

    static func content(_ id: String, _ version: Int, _ text: String = "# Hello") -> ArtifactContent
    {
        ArtifactContent(
            artifactID: id, version: version, kind: .markdown, title: "Options", content: text,
            page: "<!doctype html><pre id=\"nest-md\">\(text)</pre>",
            createdAt: date("2026-10-17T09:30:00Z"))
    }
}
