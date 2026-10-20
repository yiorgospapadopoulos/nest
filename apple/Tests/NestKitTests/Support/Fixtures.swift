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

// MARK: Configuration (B97)

extension Fixture {
    /// `GET /api/configuration` as the contract shows it.
    static let configurationJSON = """
        {
          "shared": {
            "instructions": {"path": "/Users/x/.codex/AGENTS.md", "exists": true, "version": "abc"},
            "skills": {
              "folder": "/Users/x/.claude/skills",
              "items": [
                {"name": "release-notes", "description": "Writes release notes",
                 "path": "/Users/x/.claude/skills/release-notes/SKILL.md", "source": "yours",
                 "plugin": null, "engine": null, "read_only": false, "codex_enabled": true,
                 "codex_error": null},
                {"name": "brainstorming", "description": "Explores intent",
                 "path": "/p/brainstorming/SKILL.md", "source": "plugin",
                 "plugin": "superpowers", "engine": null, "read_only": true,
                 "codex_enabled": true, "codex_error": null},
                {"name": "hatch-pet", "description": null,
                 "path": "/Users/x/.codex/skills/hatch-pet/SKILL.md", "source": "engine_only",
                 "plugin": null, "engine": "codex", "read_only": false, "codex_enabled": true,
                 "codex_error": null},
                {"name": "chrome-browser", "description": "Drives Chrome",
                 "path": "/Users/x/.claude/skills/synced/chrome-browser/SKILL.md",
                 "source": "synced", "plugin": null, "engine": null, "read_only": true,
                 "codex_enabled": false, "codex_error": null},
                {"name": "no-description", "description": null,
                 "path": "/Users/x/.claude/skills/no-description/SKILL.md", "source": "yours",
                 "plugin": null, "engine": null, "read_only": false, "codex_enabled": true,
                 "codex_error": "missing field description"}
              ]
            },
            "mcp_servers": [
              {"name": "context7", "summary": "https://mcp.context7.com/mcp", "transport": "http",
               "engines": ["codex", "claude"], "convertible": true, "reason": null},
              {"name": "linear", "summary": "https://mcp.linear.app/sse", "transport": "sse",
               "engines": ["claude"], "convertible": false, "reason": "Codex cannot use SSE"}
            ]
          },
          "engines": [
            {
              "id": "claude", "name": "Claude", "account": "giorgos@example.com · Max plan",
              "bundled_version": "2.1.286",
              "standalone": {"path": "/opt/homebrew/bin/claude", "version": "2.1.160"},
              "config_folder": "/Users/x/.claude",
              "uses_shared": {"instructions": {"on": true, "fixed": false},
                              "skills": {"on": true, "fixed": true},
                              "mcp_servers": {"on": true, "fixed": false}},
              "missing_from_shared": {"instructions": true, "skills": ["a", "b"],
                                      "mcp_servers": ["playwright"]},
              "items": [
                {"kind": "plugins", "count": 8, "detail": null, "path": null, "folder": false},
                {"kind": "hooks", "count": 2, "detail": null,
                 "path": "/Users/x/.claude/settings.json", "folder": false},
                {"kind": "subagents", "count": 3, "detail": null,
                 "path": "/Users/x/.claude/agents", "folder": true},
                {"kind": "permissions", "count": 16, "detail": "14 allow · 2 deny",
                 "path": "/Users/x/.claude/settings.json", "folder": false},
                {"kind": "teleporters", "count": 1, "detail": null, "path": null, "folder": false}
              ]
            },
            {
              "id": "codex", "name": "Codex", "account": null, "bundled_version": "0.163.0",
              "standalone": null, "config_folder": "/Users/x/.codex",
              "uses_shared": {"instructions": {"on": true, "fixed": true},
                              "skills": {"on": false, "fixed": false},
                              "mcp_servers": {"on": true, "fixed": false}},
              "missing_from_shared": {"instructions": false, "skills": [], "mcp_servers": []},
              "items": []
            }
          ]
        }
        """

    static var configurationPage: ConfigurationPage {
        decode(ConfigurationPage.self, json: configurationJSON)
    }

    static let copyPreviewJSON = """
        {"instructions": {"replace": true, "engine_path": "/Users/x/.claude/CLAUDE.md",
                          "shared_path": "/Users/x/.codex/AGENTS.md"},
         "skills": {"add": ["release-notes", "swift-format-fix"], "already": ["a", "b", "c"],
                    "same_name": [{"name": "changelog",
                                   "reason": "Shared has a skill with this name"}]},
         "mcp_servers": {"add": ["playwright"], "already": ["context7", "serena"],
                         "not_convertible": [{"name": "linear", "reason": "uses SSE"}]},
         "stays": ["plugins themselves", "claude.ai connectors", "hooks"]}
        """

    static var copyPreview: CopyPreview { decode(CopyPreview.self, json: copyPreviewJSON) }
}
