import Foundation
import Observation

/// The setup guide's steps on the Mac (B130), in order. The Linux app's list has the Secret
/// Service in Dictation's place.
public enum SetupStep: String, CaseIterable, Sendable, Identifiable {
    case engine, git, github, service, tailscale, notifications, ntfy, dictation
    case firstChat = "first_chat"

    /// Also its check's id.
    public var id: String { rawValue }

    public var rail: String {
        switch self {
        case .engine: "Engine"
        case .git: "git"
        case .github: "GitHub"
        case .service: "Background service"
        case .tailscale: "Tailscale and iPhone"
        case .notifications: "Notifications"
        case .ntfy: "ntfy"
        case .dictation: "Dictation"
        case .firstChat: "First chat"
        }
    }

    public var title: String {
        switch self {
        case .engine: "Sign in to an engine"
        case .tailscale: "Pair your iPhone"
        case .firstChat: "Send your first message"
        default: rail
        }
    }

    public var subtitle: String? {
        switch self {
        case .engine: "Nest needs one. You can add the others later."
        case .firstChat: "It uses the cheapest model of your engine."
        default: nil
        }
    }

    /// Any step but the engine, without which nothing in Nest runs. The last step has nothing
    /// to skip to; Finish leaves it.
    public var canSkip: Bool { self != .engine && self != .firstChat }
}

/// A step's round mark: told apart by shape, never by colour alone.
public enum SetupMark: Sendable, Equatable {
    case ok, todo, now, skipped

    public var name: String {
        switch self {
        case .ok: "Done"
        case .todo: "Not done"
        case .now: "Open now"
        case .skipped: "Skipped"
        }
    }

    /// The rail's mark: done first, then open now, then skipped.
    public init(_ state: SetupCheck.State?, open: Bool, skipped: Bool) {
        if state == .ok {
            self = .ok
        } else if open {
            self = .now
        } else {
            self = skipped ? .skipped : .todo
        }
    }

    /// Check Nest's mark.
    public init(_ state: SetupCheck.State) {
        switch state {
        case .ok: self = .ok
        case .missing, .warning: self = .now
        case .notApplicable, .unknown: self = .todo
        }
    }
}

/// Where the guide stands while it is open; skipped steps are remembered only that long.
@MainActor @Observable
public final class SetupFlow {
    /// A guide reopened from Settings can always be left.
    public let firstRun: Bool
    public private(set) var step = SetupStep.engine
    public private(set) var skipped: Set<SetupStep> = []

    public init(firstRun: Bool) {
        self.firstRun = firstRun
    }

    private static let steps = SetupStep.allCases
    private var index: Int { Self.steps.firstIndex(of: step) ?? 0 }

    public var isFirst: Bool { index == 0 }
    public var isLast: Bool { index == Self.steps.count - 1 }

    public func open(_ step: SetupStep) {
        self.step = step
    }

    /// Continue moves on whatever the state, except on the engine step.
    public func canContinue(engineReady: Bool) -> Bool {
        step != .engine || engineReady
    }

    /// Finishing a first run needs an engine. Someone who signed out later and reopened the
    /// guide is not locked in it.
    public func canFinish(engineReady: Bool) -> Bool {
        !firstRun || engineReady
    }

    public func moveOn(engineReady: Bool) {
        guard canContinue(engineReady: engineReady), !isLast else { return }
        step = Self.steps[index + 1]
    }

    public func back() {
        guard !isFirst else { return }
        step = Self.steps[index - 1]
    }

    public func skip() {
        guard step.canSkip else { return }
        skipped.insert(step)
        step = Self.steps[index + 1]
    }
}

/// The model the first chat opens on.
public struct FirstChatModel: Sendable, Equatable {
    public let provider: String
    public let model: String

    public init(provider: String, model: String) {
        self.provider = provider
        self.model = model
    }

    /// The cheapest model of the first engine signed in, else the first local model; nil leaves
    /// the new chat's defaults.
    public static func choose(
        accounts: [EngineAccount], catalog: (String) -> ModelCatalog, local: [ModelInfo],
        defaultProvider: String?
    ) -> FirstChatModel? {
        if let account = accounts.first(where: { $0.signedIn == true }) {
            let models = catalog(account.provider)
            return (models.cheapest ?? models.defaultModel).map {
                FirstChatModel(provider: account.provider, model: $0)
            }
        }
        guard let model = local.first?.value, let defaultProvider else { return nil }
        return FirstChatModel(provider: defaultProvider, model: model)
    }
}

extension ModelCatalog {
    /// As the daemon's providers/one_off.py, cheapest first.
    private static let cheapWords = ["haiku", "nano", "mini", "lite", "flash", "luna", "small"]

    /// The first model named like a small one.
    public var cheapest: String? {
        for word in Self.cheapWords {
            let found = models.first {
                "\($0.value) \($0.displayName)".lowercased().contains(word)
            }
            if let found {
                return found.value
            }
        }
        return nil
    }
}

/// How far Tailscale has come, from what its check's fix asks for.
public enum TailscaleStage: Sendable, Equatable {
    case off, unshared, shared

    public init(_ check: SetupCheck?) {
        guard let check else {
            self = .off
            return
        }
        guard let fix = check.fix else {
            self = .shared
            return
        }
        self = fix.value.contains("serve") ? .unshared : .off
    }
}
