import Foundation

/// Which accounts the usage meter at the top right shows, on this Mac only (B98).
public struct UsageMeterChoice: Sendable, Equatable {
    /// Account ids in the user's order; accounts it does not name follow in the daemon's.
    public var order: [String]
    /// The checked accounts; nil until the user checks or unchecks one, while the active
    /// account of each engine shows.
    public var shown: Set<String>?
    /// The engines unchecked before B98: their accounts start unchecked.
    public var hiddenEngines: Set<String>

    public init(order: [String] = [], shown: Set<String>? = nil, hiddenEngines: Set<String> = []) {
        self.order = order
        self.shown = shown
        self.hiddenEngines = hiddenEngines
    }

    func shows(_ account: EngineAccount) -> Bool {
        shown?.contains(account.id) ?? (account.active && !hiddenEngines.contains(account.provider))
    }
}

/// One row of Settings > Usage > "Top bar shows" (B98).
public struct MeterAccount: Sendable, Equatable, Identifiable {
    public let id: String
    public let provider: String
    /// "Claude · Personal".
    public let name: String
    /// "Max 20x · in use", "Signed out".
    public let detail: String
    public let shown: Bool
}

/// One line of the usage meter: an account's windows, nil before it reported any.
public struct UsageMeterLine: Sendable, Equatable, Identifiable {
    public let id: String
    public let provider: String
    /// "Claude · Personal", for the tooltip.
    public let name: String
    /// The account's title on the chip, only when both lines are of one engine.
    public let title: String?
    public let chip: UsageChip?
}

/// One account's windows in the usage popover, under "<Engine> · <title>".
public struct UsageLimitGroup: Sendable, Equatable, Identifiable {
    public let id: String
    public let provider: String
    public let title: String
    /// Turns run on it: "in use".
    public let active: Bool
    public let limits: UsageLimits?

    public init(id: String, provider: String, title: String, active: Bool, limits: UsageLimits?) {
        self.id = id
        self.provider = provider
        self.title = title
        self.active = active
        self.limits = limits
    }
}

/// The usage meter's accounts: the list to choose them in, the chip's lines and the
/// popover's groups.
public enum UsageMeter {
    /// The chip shows this many lines at most.
    public static let chipLines = 2

    /// Every account, in the user's order.
    public static func entries(_ accounts: [EngineAccount], choice: UsageMeterChoice)
        -> [MeterAccount]
    {
        ordered(accounts, choice).map { account in
            let state = account.signedIn == false ? "Signed out" : account.plan
            let detail = [state, account.active ? "in use" : nil].compactMap { $0 }
            return MeterAccount(
                id: account.id, provider: account.provider, name: name(account),
                detail: detail.joined(separator: " · "), shown: choice.shows(account))
        }
    }

    /// The chip's lines: the top two checked accounts that are not signed out.
    public static func lines(_ accounts: [EngineAccount], choice: UsageMeterChoice, now: Date)
        -> [UsageMeterLine]
    {
        let shown = Array(shownAccounts(accounts, choice).prefix(chipLines))
        guard !shown.isEmpty else {
            return [
                UsageMeterLine(
                    id: ProviderInfo.claude, provider: ProviderInfo.claude,
                    name: AccountText.engine(ProviderInfo.claude), title: nil, chip: nil)
            ]
        }
        let oneEngine = shown.count > 1 && Set(shown.map(\.provider)).count == 1
        return shown.map { account in
            UsageMeterLine(
                id: account.id, provider: account.provider, name: name(account),
                title: oneEngine ? account.title : nil,
                chip: UsageChip.of(account.usageLimits, now: now))
        }
    }

    /// The popover's groups: every checked account that is not signed out.
    public static func groups(_ accounts: [EngineAccount], choice: UsageMeterChoice)
        -> [UsageLimitGroup]
    {
        let shown = shownAccounts(accounts, choice)
        guard !shown.isEmpty else {
            return [
                UsageLimitGroup(
                    id: ProviderInfo.claude, provider: ProviderInfo.claude,
                    title: AccountText.engine(ProviderInfo.claude), active: true, limits: nil)
            ]
        }
        return shown.map { account in
            UsageLimitGroup(
                id: account.id, provider: account.provider, title: name(account),
                active: account.active, limits: account.usageLimits)
        }
    }

    /// "Claude · Personal: 5 hour: 30%, resets in 2h. Codex · Codex: not reported yet".
    public static func tooltip(_ lines: [UsageMeterLine]) -> String {
        lines.map { "\($0.name): \($0.chip?.tooltip ?? "not reported yet")" }
            .joined(separator: ". ")
    }

    /// The ids with `id` moved by `offset` places, as Alt and an arrow key move it; a move
    /// past either end changes nothing.
    public static func moved(_ ids: [String], _ id: String, by offset: Int) -> [String] {
        guard let index = ids.firstIndex(of: id), ids.indices.contains(index + offset) else {
            return ids
        }
        return moved(ids, from: index, to: index + offset)
    }

    /// The ids with the one at `from` placed at `to`, as a drag ends.
    public static func moved(_ ids: [String], from: Int, to: Int) -> [String] {
        var ids = ids
        ids.insert(ids.remove(at: from), at: to)
        return ids
    }

    private static func name(_ account: EngineAccount) -> String {
        "\(AccountText.engine(account.provider)) · \(account.title)"
    }

    /// Checked and not signed out, in the user's order; else the first active account, so
    /// the meter stays.
    private static func shownAccounts(_ accounts: [EngineAccount], _ choice: UsageMeterChoice)
        -> [EngineAccount]
    {
        let shown = ordered(accounts, choice).filter {
            choice.shows($0) && $0.signedIn != false
        }
        return shown.isEmpty ? accounts.filter(\.active).prefix(1).map { $0 } : shown
    }

    private static func ordered(_ accounts: [EngineAccount], _ choice: UsageMeterChoice)
        -> [EngineAccount]
    {
        let named = choice.order.compactMap { id in accounts.first { $0.id == id } }
        return named + accounts.filter { !choice.order.contains($0.id) }
    }
}
