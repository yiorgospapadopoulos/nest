import Foundation

/// Where the engine updates stand, as `GET /api/updates` and `updates.changed` say (B121).
public struct EngineUpdates: Codable, Sendable, Hashable {
    public enum Phase: String, Codable, Sendable {
        case idle = "none"
        case checking, preparing, ready
    }

    public var state: Phase
    /// What Relaunch changes; only while `state` is ready.
    public var engines: [EngineUpdate]
    /// The chats a relaunch would interrupt right now.
    public var busyChats: Int
    public var canUndo: Bool
    /// A plain sentence for the user, until dismissed.
    public var notice: String?

    public init(
        state: Phase = .idle, engines: [EngineUpdate] = [], busyChats: Int = 0,
        canUndo: Bool = false, notice: String? = nil
    ) {
        self.state = state
        self.engines = engines
        self.busyChats = busyChats
        self.canUndo = canUndo
        self.notice = notice
    }

    enum CodingKeys: String, CodingKey {
        case state, engines, notice
        case busyChats = "busy_chats"
        case canUndo = "can_undo"
    }
}

public struct EngineUpdate: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var name: String
    public var current: String
    public var new: String

    public init(id: String, name: String, current: String, new: String) {
        self.id = id
        self.name = name
        self.current = current
        self.new = new
    }

    /// Such as "Claude Code 2.1.317 → 2.1.318".
    public var change: String { "\(name) \(current) → \(new)" }
}
