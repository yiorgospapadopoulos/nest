import Foundation
import Observation

/// The setup guide's steps on the Mac (B130), in order. The Linux app's list has the Secret
/// Service in Dictation's place. ntfy is the optional part of Notifications.
public enum SetupStep: String, CaseIterable, Sendable, Identifiable {
    case engine, git, github, service, tailscale, notifications, dictation
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

    /// What each one is, in a line: its name and what it is, nothing on how to use it (the
    /// user, 2026-11-07).
    public var subtitle: String? {
        switch self {
        case .engine: "The coding agent: Claude Code or Codex on your own plan, or a local model."
        case .git: "Version control for your code."
        case .github: "Hosts your repositories, pull requests and code reviews."
        case .service: "Nest's own server, running on this Mac."
        case .tailscale: "A private network between your own devices."
        case .notifications: "macOS notifications from Nest."
        case .dictation: "macOS speech to text."
        case .firstChat: "One message to check it all works."
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
    /// A guide opened from Settings, as Pair a device opens Tailscale's step, can always be
    /// left.
    public let firstRun: Bool
    public private(set) var step: SetupStep
    public private(set) var skipped: Set<SetupStep> = []

    public init(firstRun: Bool, start: SetupStep = .engine) {
        self.firstRun = firstRun
        step = start
    }

    /// The engine step is done when the daemon's check is (Claude Code, Codex or local
    /// models), or when another engine is ready, signed in under More engines.
    public nonisolated static func engineReady(
        _ check: SetupCheck?, providers: [ProviderInfo]
    ) -> Bool {
        check?.state == .ok || EngineSetup.others(providers).contains(where: \.ready)
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

/// What the main window shows (B130).
public enum WindowContent: Sendable, Equatable {
    /// Its background only: whether the guide shows is not known yet.
    case blank
    case daemonDown
    case guide
    case projects

    /// `firstRun` is nil until the daemon was asked. A first run whose guide is not up yet
    /// stays blank too: the projects never show for a moment before the guide.
    public init(daemonDown: Bool, guideOpen: Bool, firstRun: Bool?) {
        if daemonDown {
            self = .daemonDown
        } else if guideOpen {
            self = .guide
        } else if firstRun == false {
            self = .projects
        } else {
            self = .blank
        }
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

/// How far Tailscale has come, as its check's `stage` says; before its answer, the start.
public enum TailscaleStage: String, Sendable, Equatable {
    case install, connect, share, pair, done

    public init(_ check: SetupCheck?) {
        self = check?.stage.flatMap(Self.init(rawValue:)) ?? .install
    }

    /// Whether the phone can reach Nest, after the sharing step: before it, a pairing code is
    /// no use, so it does not show.
    public var reachable: Bool { self == .pair || self == .done }
}
