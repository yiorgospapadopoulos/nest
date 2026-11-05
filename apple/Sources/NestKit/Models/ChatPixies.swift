import Foundation

// The pixies a project chat called, kept as its group until sent away, and what each
// call and each subagent did (B46, `GET /api/sessions/{id}/pixies` and friends).

/// How a pixie's latest call in a chat went.
public enum PixieCallState: String, UnknownSafeEnum {
    case running, done, failed, interrupted
    case unknown

    /// The word the tree and the work page show.
    public var label: String {
        switch self {
        case .running: "working"
        case .done: "done"
        case .failed: "failed"
        case .interrupted: "interrupted"
        case .unknown: "idle"
        }
    }

    public var isRunning: Bool { self == .running }
}

/// One call of a pixie in a chat: its Agent call, or a SendMessage that continued the same
/// agent with its earlier work in context.
public struct ChatPixieCall: Decodable, Sendable, Hashable, Identifiable {
    public var id: String
    public var pixieID: String
    public var toolUseID: String
    /// The subagent's id, once Claude Code named it.
    public var agentID: String?
    public var state: PixieCallState
    /// It continued an earlier call's agent.
    public var continued: Bool
    public var startedAt: Date
    public var finishedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, state, continued
        case pixieID = "pixie_id"
        case toolUseID = "tool_use_id"
        case agentID = "agent_id"
        case startedAt = "started_at"
        case finishedAt = "finished_at"
    }
}

/// A pixie of a team the chat called, with its latest call's state with the team; nil
/// while it was not called yet.
public struct ChatTeamMember: Decodable, Sendable, Hashable {
    public var pixieID: String
    public var leader: Bool
    public var state: PixieCallState?

    enum CodingKeys: String, CodingKey {
        case leader, state
        case pixieID = "pixie_id"
    }
}

/// A solo pixie or a team a chat called, in the order first called; it stays after it
/// finishes until it is sent away. Calls are newest first.
public struct ChatPixieEntry: Decodable, Sendable, Hashable, Identifiable {
    public enum Kind: String, UnknownSafeEnum {
        case pixie, team
        case unknown
    }

    public var kind: Kind
    public var pixieID: String?
    public var teamID: String?
    /// The latest call's.
    public var state: PixieCallState
    /// A team's pixies, the leader marked; empty for a solo pixie.
    public var members: [ChatTeamMember]
    public var calls: [ChatPixieCall]

    public var id: String {
        kind == .team ? "team:\(teamID ?? "")" : "pixie:\(pixieID ?? "")"
    }

    /// What Send away asks for: the team with its members, or the pixie.
    public var sendAway: SendAwayRequest {
        kind == .team ? SendAwayRequest(teamID: teamID) : SendAwayRequest(pixieID: pixieID)
    }

    enum CodingKeys: String, CodingKey {
        case kind, state, members, calls
        case pixieID = "pixie_id"
        case teamID = "team_id"
    }
}

/// `POST /api/sessions/{id}/pixies/send-away`: exactly one of the two.
public struct SendAwayRequest: Encodable, Sendable, Hashable {
    public var pixieID: String?
    public var teamID: String?

    public init(pixieID: String? = nil, teamID: String? = nil) {
        self.pixieID = pixieID
        self.teamID = teamID
    }

    enum CodingKeys: String, CodingKey {
        case pixieID = "pixie_id"
        case teamID = "team_id"
    }
}

/// What a work page shows, read-only (B46): a subagent's transcript, a pixie's calls in a
/// chat, or a team's (all its members' calls).
public enum WorkTarget: Sendable, Hashable {
    case subagent(session: String, toolUseID: String)
    case pixie(session: String, pixieID: String)
    case team(session: String, teamID: String, members: [String])

    /// The chat the work belongs to.
    public var session: String {
        switch self {
        case .subagent(let session, _), .pixie(let session, _), .team(let session, _, _):
            session
        }
    }
}
