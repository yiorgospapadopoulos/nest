import Foundation

/// One row of More engines in Settings > Accounts (B107): an engine past Claude and Codex,
/// its labels, its state in a word and its one action.
public struct EngineSetup: Sendable, Equatable {
    /// What the row's button does.
    public enum Action: Sendable, Equatable {
        case none
        /// Nest fetches the engine; `again` after a failed install.
        case install(again: Bool)
        /// The engine's login command, run in Terminal.
        case signIn(command: String)
        /// A key field the button reveals.
        case addKey(placeholder: String)
        case removeKey
    }

    /// Engines the user installs themselves, which Nest does not fetch.
    static let installedByUser: Set<String> = ["cursor"]

    public static let gitWarningText =
        "Nest cannot block this engine's git commands, so it may commit or push on its own."

    public let name: String
    public let title: String
    public let version: String?
    /// "untested".
    public let labels: [String]
    /// "Ready", "Signed out", "Not checked", "No key", "Not installed", "Installing" or
    /// "Install failed".
    public let state: String
    public var ready: Bool { state == "Ready" }
    public let installing: Bool
    /// Why installing failed, in plain words.
    public let failure: String?
    public let action: Action
    /// Shown only as the warning mark's help and accessibility label.
    public let gitWarning: String?

    public init(_ provider: ProviderInfo) {
        name = provider.name
        title = provider.displayName
        version = provider.version
        labels = provider.tested ? [] : ["untested"]
        gitWarning = provider.gitGuard ? nil : Self.gitWarningText
        installing = provider.state == .installing
        failure = provider.state == .installFailed ? provider.stateDetail : nil
        let canInstall = !Self.installedByUser.contains(provider.name)
        switch provider.state {
        case .ready:
            (state, action) = Self.signIn(of: provider)
        case .installing:
            (state, action) = ("Installing", .none)
        case .notInstalled:
            (state, action) = ("Not installed", canInstall ? .install(again: false) : .none)
        case .installFailed:
            (state, action) = ("Install failed", canInstall ? .install(again: true) : .none)
        case .unknown:
            (state, action) = ("Not ready", .none)
        }
    }

    /// The other engines' rows, in the daemon's order: every engine but Claude and Codex,
    /// whose sections stay their own.
    public static func others(_ providers: [ProviderInfo]) -> [EngineSetup] {
        providers.filter { ![ProviderInfo.claude, "codex"].contains($0.name) }
            .map(EngineSetup.init)
    }

    private static func signIn(of provider: ProviderInfo) -> (String, Action) {
        let signedIn = provider.signedIn
        switch provider.signIn {
        case .apiKey:
            if signedIn == true { return ("Ready", .removeKey) }
            return ("No key", .addKey(placeholder: "Paste your \(provider.displayName) API key"))
        case .terminal, .unknown:
            let state =
                signedIn == true ? "Ready" : signedIn == false ? "Signed out" : "Not checked"
            if signedIn != true, let command = provider.loginCommand {
                return (state, .signIn(command: command))
            }
            return (state, .none)
        case .browser:
            return (signedIn == false ? "Signed out" : "Ready", .none)
        }
    }
}
