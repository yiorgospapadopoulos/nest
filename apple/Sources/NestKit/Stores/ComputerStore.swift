import Foundation
import Observation

/// Computer use (B150): Settings > Computer use, and what each chat holds now with its
/// latest screenshot, for the composer's preview.
@MainActor @Observable
public final class ComputerStore {
    /// Nil until loaded.
    public private(set) var settings: ComputerUseSettings?
    /// Nil until loaded.
    public private(set) var status: ComputerStatus?
    /// The targets each chat holds now, by session id; a chat that holds none is absent.
    public private(set) var held: [String: [ComputerTarget]] = [:]
    /// Each chat's latest frame, as announced.
    public private(set) var frames: [String: ComputerFrame] = [:]
    /// Each chat's latest screenshot read, with the seq it was read for.
    public private(set) var images: [String: (seq: Int, png: Data)] = [:]

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Whether the composers offer the chat's switch.
    public var enabled: Bool { settings?.enabled == true }

    /// The latest frame announced for the chat.
    public func frame(of session: String) -> ComputerFrame? {
        frames[session]
    }

    public func targets(of session: String) -> [ComputerTarget] {
        held[session] ?? []
    }

    /// Every app a chat is using now, for the glow on each one's screen.
    public var inUse: [ComputerTarget] {
        held.values.flatMap { $0 }
    }

    /// The latest screenshot read for the chat.
    public func image(of session: String) -> Data? {
        images[session]?.png
    }

    public func loadSettings() async throws {
        settings = try await api.computerSettings()
    }

    public func loadStatus() async throws {
        status = try await api.computerStatus()
    }

    /// Shows the change at once and restores the old settings if the daemon refuses it.
    /// The whole section is sent, so it is read first when it was not yet.
    public func update(_ change: (inout ComputerUseSettings) -> Void) async throws {
        if settings == nil {
            try await loadSettings()
        }
        guard let previous = settings else { return }
        var changed = previous
        change(&changed)
        settings = changed
        do {
            settings = try await api.updateComputerSettings(changed)
        } catch {
            settings = previous
            throw error
        }
    }

    /// Asks macOS; the status is read again when the user comes back from System Settings.
    public func ask(_ permission: ComputerPermission) async throws {
        _ = try await api.askComputerPermission(permission)
        try await loadStatus()
    }

    /// Reads the chat's screenshot when a newer frame was announced than the one read.
    public func loadFrame(of session: String) async {
        guard let frame = frames[session], images[session]?.seq != frame.seq,
            let png = try? await api.computerFrame(session)
        else { return }
        images[session] = (frame.seq, png)
    }

    /// What was held is known only from events: a new connection forgets it, and the next
    /// frames of a chat that still holds something show it again.
    public func reset() {
        held = [:]
        frames = [:]
        images = [:]
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .computerState(let targets):
            guard let id = event.sessionID else { return }
            if targets.isEmpty {
                forget(id)
            } else {
                held[id] = targets
            }
        case .computerFrame(let frame):
            guard let id = event.sessionID else { return }
            frames[id] = frame
            // Frames come only while the chat holds the target, so one seen before its
            // state, as after a reconnect, still shows the preview.
            if !(held[id] ?? []).contains(where: { $0.key == frame.target }) {
                held[id, default: []].append(Self.target(of: frame))
            }
        case .sessionDeleted(let id):
            forget(id)
        default:
            break
        }
    }

    private func forget(_ session: String) {
        held[session] = nil
        frames[session] = nil
        images[session] = nil
    }

    /// The target a frame shows, named from its label ("TextEdit: Notes.rtf").
    private static func target(of frame: ComputerFrame) -> ComputerTarget {
        let name = frame.label.components(separatedBy: ": ").first ?? ""
        return ComputerTarget(
            key: frame.target, name: name.isEmpty ? ComputerTarget.name(of: frame.target) : name)
    }
}
