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
    /// A new Nest that Relaunch installs (B130).
    public var app: AppUpdate?
    /// The app that belongs to the running daemon; an app of another version swaps to it.
    public var appFile: AppFile?

    public init(
        state: Phase = .idle, engines: [EngineUpdate] = [], busyChats: Int = 0,
        canUndo: Bool = false, notice: String? = nil, app: AppUpdate? = nil,
        appFile: AppFile? = nil
    ) {
        self.state = state
        self.engines = engines
        self.busyChats = busyChats
        self.canUndo = canUndo
        self.notice = notice
        self.app = app
        self.appFile = appFile
    }

    enum CodingKeys: String, CodingKey {
        case state, engines, notice, app
        case busyChats = "busy_chats"
        case canUndo = "can_undo"
        case appFile = "app_file"
    }
}

/// What Relaunch would install of Nest itself.
public struct AppUpdate: Codable, Sendable, Hashable {
    public var version: String
    public var notes: String

    public init(version: String, notes: String) {
        self.version = version
        self.notes = notes
    }

    /// Such as "Nest 1.2.0".
    public var change: String { "Nest \(version)" }
}

/// A release's app on this machine: the zip the release made with `ditto`.
public struct AppFile: Codable, Sendable, Hashable {
    public var version: String
    public var path: String

    public init(version: String, path: String) {
        self.version = version
        self.path = path
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
