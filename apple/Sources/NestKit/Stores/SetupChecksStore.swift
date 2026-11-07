import Foundation
import Observation

/// The setup checks of the guide and Check Nest, and the bug report (B130).
@MainActor @Observable
public final class SetupChecksStore {
    /// Nil until the first answer; they can take several seconds.
    public private(set) var checks: [SetupCheck]?
    public private(set) var checking = false
    public private(set) var reporting = false
    @ObservationIgnored private var latest = 0

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Asks again; only the latest question's answer counts. A failed one keeps what is known.
    public func refresh() async {
        latest += 1
        let asked = latest
        checking = true
        let found = try? await api.setupChecks()
        guard asked == latest else { return }
        checks = found ?? checks
        checking = false
    }

    public func makeReport() async throws -> SetupReport {
        reporting = true
        defer { reporting = false }
        return try await api.setupReport()
    }
}
