import Foundation
import Observation

/// The setup checks of the guide and Check Nest, and the bug report (B130).
@MainActor @Observable
public final class SetupChecksStore {
    /// Nil until the first answer; they can take several seconds.
    public private(set) var checks: [SetupCheck]?
    public private(set) var checking = false
    public private(set) var reporting = false
    /// `tailscale serve` is being run.
    public private(set) var sharing = false
    @ObservationIgnored private var latest = 0

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Asks again; only the latest question's answer counts. A failed one keeps what is known.
    public func refresh() async {
        _ = await ask()
    }

    /// Whether a pairing code must wait for Nest to be shared on the tailnet, asked afresh:
    /// before that the phone cannot reach Nest. Checks that cannot answer leave pairing as it
    /// was.
    public func pairingNeedsSharing() async -> Bool {
        guard let tailscale = await ask()?.first(where: { $0.id == SetupStep.tailscale.id })
        else { return false }
        return !TailscaleStage(tailscale).reachable
    }

    /// This question's own answer, nil when it failed.
    private func ask() async -> [SetupCheck]? {
        latest += 1
        let asked = latest
        checking = true
        let found = try? await api.setupChecks()
        if asked == latest {
            checks = found ?? checks
            checking = false
        }
        return found
    }

    /// `answers` are the app's own for the checks only it can make (`SystemAnswers`).
    public func makeReport(answers: [SetupCheck]) async throws -> SetupReport {
        reporting = true
        defer { reporting = false }
        return try await api.setupReport(answers: answers)
    }

    /// Shares Nest on the tailnet: the answer takes the Tailscale check's place, as it can
    /// carry Tailscale's link to turn HTTPS on, until the checks are asked again. Past the
    /// sharing step they are asked again at once, for the pairing that follows.
    public func shareTailscale() async throws {
        sharing = true
        defer { sharing = false }
        let answer = try await api.shareTailscale()
        if let index = checks?.firstIndex(where: { $0.id == answer.id }) {
            checks?[index] = answer
        }
        if answer.stage != TailscaleStage.share.rawValue {
            await refresh()
        }
    }
}
