import Foundation

/// One usage window of an account (B98), shortest first in its list.
public struct AccountLimit: Codable, Sendable, Hashable {
    /// "5 hour", "Weekly", "30 day", or a per-model one's "Fable weekly" (B161).
    public var label: String
    /// The model a per-model window is for, such as "Fable"; nil for the account's own
    /// windows. The usage chip leaves these out (B161).
    public var scope: String?
    public var minutes: Int
    /// A fraction from 0 to 1.
    public var utilization: Double
    public var resetsAt: Date?
    public var updatedAt: Date?
    /// The window passed its reset time since it was reported: 0 used, no reset time,
    /// until a newer report.
    public var reset: Bool

    public init(
        label: String, minutes: Int, utilization: Double, resetsAt: Date?, updatedAt: Date?,
        reset: Bool = false, scope: String? = nil
    ) {
        self.label = label
        self.scope = scope
        self.minutes = minutes
        self.utilization = utilization
        self.resetsAt = resetsAt
        self.updatedAt = updatedAt
        self.reset = reset
    }

    enum CodingKeys: String, CodingKey {
        case label, scope, minutes, utilization, reset
        case resetsAt = "resets_at"
        case updatedAt = "updated_at"
    }

    /// The window as the usage views draw it.
    public var window: LimitWindow {
        LimitWindow(
            utilization: reset ? 0 : utilization, resetsAt: reset ? nil : resetsAt,
            updatedAt: updatedAt, minutes: minutes, label: label, reset: reset)
    }
}

/// One subscription of one engine (B98): the user's first login, or one added in Nest.
/// Exactly one account per engine is active; turns run on it.
public struct EngineAccount: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var provider: String
    /// The user's own name for it.
    public var name: String?
    /// The name, else the email, else the engine's name.
    public var title: String
    public var email: String?
    /// Such as "Max 20x".
    public var plan: String?
    /// Nil while the engine could not be asked.
    public var signedIn: Bool?
    public var active: Bool
    /// The login that was there before Nest; it cannot be removed.
    public var first: Bool
    /// A sign-in waits on the browser.
    public var signingIn: Bool
    /// Why the last sign-in failed.
    public var error: String?
    public var limits: [AccountLimit]
    /// Codex's resets kept for later (Round 2 of B98); nil for Claude, which has none.
    public var bankedResets: BankedResets?
    public var checkedAt: Date?
    /// A signed-in Claude account, which can open Claude Code's limit reset (B161); only
    /// Claude Code in the terminal knows whether it holds one. Nil from an older daemon.
    public var limitReset: Bool?

    public init(
        id: String, provider: String, name: String? = nil, title: String, email: String? = nil,
        plan: String? = nil, signedIn: Bool?, active: Bool, first: Bool,
        signingIn: Bool = false, error: String? = nil, limits: [AccountLimit] = [],
        bankedResets: BankedResets? = nil, checkedAt: Date? = nil, limitReset: Bool? = nil
    ) {
        self.id = id
        self.provider = provider
        self.name = name
        self.title = title
        self.email = email
        self.plan = plan
        self.signedIn = signedIn
        self.active = active
        self.first = first
        self.signingIn = signingIn
        self.error = error
        self.limits = limits
        self.bankedResets = bankedResets
        self.checkedAt = checkedAt
        self.limitReset = limitReset
    }

    enum CodingKeys: String, CodingKey {
        case id, provider, name, title, email, plan, active, first, error, limits
        case signedIn = "signed_in"
        case signingIn = "signing_in"
        case bankedResets = "banked_resets"
        case checkedAt = "checked_at"
        case limitReset = "limit_reset"
    }

    /// Its windows for the usage views; nil before any was reported.
    public var usageLimits: UsageLimits? {
        limits.isEmpty ? nil : UsageLimits(windows: limits.map(\.window))
    }

    /// Its own windows for the chip, without the per-model ones, which only the popover
    /// and Settings show (B161); nil before any was reported.
    public var chipLimits: UsageLimits? {
        let own = limits.filter { $0.scope == nil }
        return own.isEmpty ? nil : UsageLimits(windows: own.map(\.window))
    }

    /// Settings > Accounts offers Claude Code's limit reset for it (B161).
    public var offersLimitReset: Bool { limitReset == true }
}

/// A Codex account's banked resets: how many are available, and each one once its details
/// were read (`GET /api/accounts/{id}/banked-resets`); nil before that.
public struct BankedResets: Codable, Sendable, Hashable {
    public var available: Int
    public var credits: [BankedCredit]?

    public init(available: Int, credits: [BankedCredit]?) {
        self.available = available
        self.credits = credits
    }
}

/// One banked reset, used with its id.
public struct BankedCredit: Codable, Sendable, Hashable, Identifiable {
    public var id: String
    public var title: String?
    public var description: String?
    public var expiresAt: Date?

    public init(id: String, title: String?, description: String?, expiresAt: Date?) {
        self.id = id
        self.title = title
        self.description = description
        self.expiresAt = expiresAt
    }

    enum CodingKeys: String, CodingKey {
        case id, title, description
        case expiresAt = "expires_at"
    }
}

/// What using a banked reset did.
public enum BankedResetOutcome: String, UnknownSafeEnum {
    case reset
    case nothingToReset = "nothing_to_reset"
    case noCredit = "no_credit"
    case alreadyRedeemed = "already_redeemed"
    case unknown
}

/// `POST /api/accounts/{id}/banked-resets/use`: the outcome and every account after it.
public struct BankedResetUse: Codable, Sendable, Hashable {
    public var outcome: BankedResetOutcome
    public var accounts: [EngineAccount]

    public init(outcome: BankedResetOutcome, accounts: [EngineAccount]) {
        self.outcome = outcome
        self.accounts = accounts
    }
}

struct UseBankedResetRequest: Encodable {
    var creditID: String

    enum CodingKeys: String, CodingKey {
        case creditID = "credit_id"
    }
}

/// `GET /api/accounts` and the `accounts.changed` event: Claude's accounts, then Codex's.
public struct AccountList: Codable, Sendable, Hashable {
    public var accounts: [EngineAccount]

    public init(accounts: [EngineAccount]) {
        self.accounts = accounts
    }
}

/// A sign-in that started: the account, and for Codex the page to open in the browser; for
/// an engine signed in from Terminal, the command to run there (B107).
public struct AccountSignIn: Codable, Sendable, Hashable {
    /// Nil when the daemon answers only the command.
    public var account: EngineAccount?
    public var authURL: URL?
    public var loginCommand: String?

    public init(account: EngineAccount?, authURL: URL?, loginCommand: String? = nil) {
        self.account = account
        self.authURL = authURL
        self.loginCommand = loginCommand
    }

    enum CodingKeys: String, CodingKey {
        case account
        case authURL = "auth_url"
        case loginCommand = "login_command"
    }
}

/// `PUT /api/accounts/{id}/key`: the engine's API key, which only the daemon keeps.
struct EngineKeyRequest: Encodable {
    var key: String
}

/// `PUT /api/accounts/{id}/name`: null clears the name.
struct RenameAccountRequest: Encodable {
    var name: String?

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(name, forKey: .name)
    }

    enum CodingKeys: String, CodingKey {
        case name
    }
}
