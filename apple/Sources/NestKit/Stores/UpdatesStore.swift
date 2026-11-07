import Foundation
import Observation

/// What a restart does to the engines.
public enum UpdateRestart: Sendable {
    case relaunch, undo
}

/// What the update strip shows.
public enum UpdateStrip: Sendable, Equatable {
    case notice(String)
    case ready(app: AppUpdate?, engines: [EngineUpdate], relaunching: Bool)
}

/// An update that can be relaunched into, or is being.
public struct ReadyUpdate: Sendable, Equatable {
    /// A new Nest.
    public let app: AppUpdate?
    public let engines: [EngineUpdate]
    public let relaunching: Bool
}

/// The confirmation before a restart that would stop chats, or before any undo.
public struct RestartQuestion: Sendable, Equatable {
    public let kind: UpdateRestart
    public let title: String
    public let action: String
    public let about: String

    init(_ kind: UpdateRestart, busy: Int) {
        self.kind = kind
        switch kind {
        case .relaunch:
            title = "Relaunch to update?"
            action = "Relaunch"
        case .undo:
            title = "Undo update?"
            action = "Undo update"
        }
        switch busy {
        case 0: about = kind == .undo ? "Nest relaunches on the engines from before." : ""
        case 1: about = "1 chat is mid-turn. It will stop and can be resumed."
        default: about = "\(busy) chats are mid-turn. They will stop and can be resumed."
        }
    }
}

/// The updates of the engines (B121) and of Nest (B130): one check when the app first
/// connects, the state read on every connect and followed through `updates.changed`, and
/// the restarts that apply or undo an update. The strip's views read it; the chat lists must
/// not.
@MainActor @Observable
public final class UpdatesStore {
    /// Nil until the daemon first answers.
    public private(set) var status: EngineUpdates?
    /// The restart this app asked for, until the app quits for it or the socket connects
    /// again: the daemon reports no update as soon as it accepts a relaunch.
    public private(set) var restarting: UpdateRestart?
    /// The strip's x, for as long as this store lives: in memory only.
    public private(set) var hidden = false
    /// The confirmation on screen.
    public private(set) var asking: RestartQuestion?
    @ObservationIgnored private var checked = false
    @ObservationIgnored private var reading = false
    /// Quits and reopens the app once the daemon accepted a restart, given the new app's
    /// version when a relaunch brings one, so that one opens once (B130). Set only for This
    /// Mac's daemon: on a remote one the app stays and reconnects.
    @ObservationIgnored public var reopen: (@MainActor (String?) -> Void)?
    /// Told the app that belongs to the daemon on every connect; `AppSwapper` keeps it to
    /// once a launch. Set only for This Mac's daemon: a remote's file is on its machine.
    @ObservationIgnored public var followApp: (@MainActor (AppFile) -> Void)?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// What Settings' row shows, whether or not the strip was hidden.
    public var ready: ReadyUpdate? {
        switch restarting {
        case .undo: return nil
        case .relaunch:
            return ReadyUpdate(
                app: status?.app, engines: status?.engines ?? [], relaunching: true)
        case nil:
            guard let status, status.state == .ready,
                status.app != nil || !status.engines.isEmpty
            else { return nil }
            return ReadyUpdate(app: status.app, engines: status.engines, relaunching: false)
        }
    }

    /// What the strip shows, if anything: a notice wins until dismissed; an undo shows none.
    public var strip: UpdateStrip? {
        if restarting == nil, let notice = status?.notice {
            return .notice(notice)
        }
        guard !hidden, let ready else { return nil }
        return .ready(app: ready.app, engines: ready.engines, relaunching: ready.relaunching)
    }

    /// Whether Settings offers Undo update.
    public var offersUndo: Bool { status?.canUndo == true || restarting == .undo }

    /// A failed read keeps what is known.
    public func load() async {
        if let status = try? await api.updates() {
            self.status = status
        }
    }

    /// After every connect, which also ends a restart this app asked for. The first one
    /// asks for a check too; one that fails shows nothing.
    public func connected() async {
        await load()
        restarting = nil
        if let file = status?.appFile {
            followApp?(file)
        }
        guard !checked else { return }
        checked = true
        if let status = try? await api.checkUpdates() {
            self.status = status
        }
    }

    /// Relaunch or Undo as a button runs it: Relaunch goes straight on when no chat would
    /// stop, otherwise `asking` holds the question. The chats mid-turn are read each time,
    /// as `updates.changed` does not follow turns starting and ending.
    public func start(_ kind: UpdateRestart) async throws {
        guard !reading else { return }
        reading = true
        await load()
        reading = false
        let busy = status?.busyChats ?? 0
        if busy > 0 || kind == .undo {
            asking = RestartQuestion(kind, busy: busy)
        } else {
            try await run(kind)
        }
    }

    /// The restart itself; when the daemon refuses, the state is read again.
    public func run(_ kind: UpdateRestart) async throws {
        asking = nil
        restarting = kind
        let newApp = kind == .relaunch ? status?.app?.version : nil
        do {
            switch kind {
            case .relaunch: try await api.relaunchUpdate()
            case .undo: try await api.undoUpdate()
            }
        } catch {
            restarting = nil
            await load()
            throw error
        }
        reopen?(newApp)
    }

    public func cancel() {
        asking = nil
    }

    public func hideStrip() {
        hidden = true
    }

    public func dismissNotice() async throws {
        status = try await api.dismissUpdateNotice()
    }

    public func apply(_ event: Event) {
        if case .updatesChanged(let status) = event.body {
            self.status = status
        }
    }
}
