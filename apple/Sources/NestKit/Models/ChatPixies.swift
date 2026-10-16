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

/// A message of a subagent's own, with its tool calls and results.
public struct AgentWorkMessage: Decodable, Sendable, Hashable {
    public var eventID: Int
    public var ts: Date
    public var blocks: [MessageBlock]

    public init(eventID: Int, ts: Date, blocks: [MessageBlock]) {
        self.eventID = eventID
        self.ts = ts
        self.blocks = blocks
    }

    enum CodingKeys: String, CodingKey {
        case ts, blocks
        case eventID = "event_id"
    }
}

/// `GET /api/sessions/{id}/agents/{tool_use_id}/transcript`: what the subagent was asked,
/// its own messages so far and its report once there is one.
public struct AgentWork: Decodable, Sendable, Hashable {
    public var toolUseID: String
    public var prompt: String?
    public var messages: [AgentWorkMessage]
    public var report: String?

    enum CodingKeys: String, CodingKey {
        case prompt, messages, report
        case toolUseID = "tool_use_id"
    }
}

/// `GET /api/sessions/{id}/pixies/{pixie_id}/calls`: a call with its work.
public struct PixieCallWork: Decodable, Sendable, Hashable, Identifiable {
    public var call: ChatPixieCall
    public var prompt: String?
    public var messages: [AgentWorkMessage]
    public var report: String?

    public var id: String { call.id }

    enum CodingKeys: String, CodingKey {
        case prompt, messages, report
    }

    public init(from decoder: any Decoder) throws {
        call = try ChatPixieCall(from: decoder)
        let container = try decoder.container(keyedBy: CodingKeys.self)
        prompt = try container.decodeIfPresent(String.self, forKey: .prompt)
        messages = try container.decode([AgentWorkMessage].self, forKey: .messages)
        report = try container.decodeIfPresent(String.self, forKey: .report)
    }
}
