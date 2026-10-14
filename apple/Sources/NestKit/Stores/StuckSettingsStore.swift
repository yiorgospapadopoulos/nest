import Foundation
import Observation

/// The daemon's thresholds for flagging a chat as stuck, for the Settings section (D036).
@MainActor @Observable
public final class StuckSettingsStore {
    /// Nil until loaded.
    public private(set) var settings: StuckSettings?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func load() async throws {
        settings = try await api.stuckSettings()
    }

    /// Shows the new value at once and restores the old settings if the daemon refuses.
    public func set(_ threshold: StuckThreshold, to value: Int) async throws {
        guard let previous = settings else { return }
        var changed = previous
        changed[keyPath: threshold.keyPath] = value
        settings = changed
        do {
            settings = try await api.updateStuckSettings(changed)
        } catch {
            settings = previous
            throw error
        }
    }
}
