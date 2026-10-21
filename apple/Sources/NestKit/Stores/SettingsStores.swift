import Foundation
import Observation

/// Settings > General > Storage: what Nest keeps, archiving idle chats, the largest
/// attachments and rebuilding the search index (B81).
@MainActor @Observable
public final class StorageStore {
    public private(set) var usage: StorageUsage?
    public private(set) var settings: StorageSettings?
    /// The largest attachments, once Review large attachments read them.
    public private(set) var attachments: [LargeAttachment]?
    public private(set) var deleting: Set<String> = []
    public private(set) var isRebuilding = false

    /// How many attachments the review lists.
    public static let reviewLimit = 20

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func load() async throws {
        usage = try await api.storage()
        settings = try await api.storageSettings()
    }

    /// Shows the choice at once and restores the old one if the daemon refuses it.
    public func setArchiveAfterDays(_ days: Int?) async throws {
        let previous = settings
        settings = StorageSettings(archiveAfterDays: days)
        do {
            settings = try await api.updateStorageSettings(StorageSettings(archiveAfterDays: days))
        } catch {
            settings = previous
            throw error
        }
    }

    public func loadAttachments() async throws {
        attachments = try await api.largeAttachments(limit: Self.reviewLimit)
    }

    public func closeAttachments() {
        attachments = nil
    }

    /// Deletes the attachment for good, then reads the space used again.
    public func delete(_ attachment: LargeAttachment) async throws {
        deleting.insert(attachment.id)
        defer { deleting.remove(attachment.id) }
        try await api.deleteAttachment(attachment.id)
        attachments?.removeAll { $0.id == attachment.id }
        if let fresh = try? await api.storage() {
            usage = fresh
        }
    }

    public func rebuildSearch() async throws {
        isRebuilding = true
        defer { isRebuilding = false }
        try await api.rebuildSearch()
    }
}

/// Settings > Pixies: what new pixies start with and the habits' switches (B81).
@MainActor @Observable
public final class PixieSettingsStore {
    /// Nil until loaded.
    public private(set) var settings: PixieSettings?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func load() async throws {
        settings = try await api.pixieSettings()
    }

    /// Shows the change at once and restores the old settings if the daemon refuses it.
    /// The whole section is sent, so it is read first when it was not yet.
    public func update(_ change: (inout PixieSettings) -> Void) async throws {
        if settings == nil {
            try await load()
        }
        guard let previous = settings else { return }
        var changed = previous
        change(&changed)
        settings = changed
        do {
            settings = try await api.updatePixieSettings(changed)
        } catch {
            settings = previous
            throw error
        }
    }
}

/// Settings > Notifications: the pixie report level the daemon keeps for the phone (B85).
@MainActor @Observable
public final class NotificationRulesStore {
    /// Nil until loaded.
    public private(set) var rules: NotificationRules?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func load() async throws {
        rules = try await api.notificationRules()
    }

    /// Shows the level at once and restores the old one if the daemon refuses it. The
    /// whole section is sent, so it is read first when it was not yet.
    public func setPixieReportLevel(_ level: ReportSeverity) async throws {
        if rules == nil {
            try await load()
        }
        guard let previous = rules else { return }
        var changed = previous
        changed.pixieReportLevel = level
        rules = changed
        do {
            rules = try await api.updateNotificationRules(changed)
        } catch {
            rules = previous
            throw error
        }
    }
}

/// Settings > Accounts: every engine's accounts, one active per engine (B98), and the
/// `gh` login (B81). Also the limits the usage meter shows, and their manual refresh.
@MainActor @Observable
public final class AccountsStore {
    /// Claude's accounts, then Codex's, as the daemon orders them.
    public private(set) var accounts: [EngineAccount] = []
    public private(set) var github: GitHubAccount?
    public private(set) var isCheckingGitHub = false
    /// A manual refresh of the limits is on its way.
    public private(set) var isRefreshing = false
    /// The daemon refuses another refresh until then.
    public private(set) var retryAt: Date?
    /// Why the last manual refresh failed, other than being too soon.
    public private(set) var refreshFailure: String?
    /// Accounts with a sign out or removal on its way.
    private var busy: Set<String> = []
    /// Codex accounts' banked resets with their details, by account id, once read.
    public private(set) var bankedResets: [String: BankedResets] = [:]

    let api: any NestAPI
    let calendar: Calendar
    let now: @Sendable () -> Date

    public init(
        api: any NestAPI, calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.api = api
        self.calendar = calendar
        self.now = now
    }

    public func load() async throws {
        accounts = try await api.engineAccounts()
    }

    public func accounts(of provider: String) -> [EngineAccount] {
        accounts.filter { $0.provider == provider }
    }

    public func account(_ id: String) -> EngineAccount? {
        accounts.first { $0.id == id }
    }

    public func isBusy(_ id: String) -> Bool {
        busy.contains(id)
    }

    /// Adds an account of the engine and starts its sign-in; answers the page to open in
    /// the browser when the engine has one (Codex), and `accounts.changed` tells the outcome.
    public func add(_ provider: String) async throws -> URL? {
        let started = try await api.addAccount(provider: provider)
        put(started.account)
        return started.authURL
    }

    public func signIn(_ id: String) async throws -> URL? {
        let started = try await api.signInAccount(id)
        put(started.account)
        return started.authURL
    }

    public func cancelSignIn(_ id: String) async throws {
        try await api.cancelAccountSignIn(id)
    }

    public func signOut(_ id: String) async throws {
        busy.insert(id)
        defer { busy.remove(id) }
        put(try await api.signOutAccount(id))
    }

    /// Trimmed; empty clears the user's name. An unchanged one is not sent, nor the title
    /// of an account without a name.
    public func rename(_ id: String, to text: String) async throws {
        guard let account = account(id) else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let name = trimmed.isEmpty ? nil : trimmed
        guard name != account.name, account.name != nil || name != account.title else { return }
        put(try await api.renameAccount(id, name: name))
    }

    /// Moves the check at once, and back if the daemon refuses. A signed-out account
    /// cannot take it.
    public func activate(_ id: String) async throws {
        guard let account = account(id), !account.active, account.signedIn == true else {
            return
        }
        let previous = accounts
        accounts = accounts.map { other in
            guard other.provider == account.provider else { return other }
            var other = other
            other.active = other.id == id
            return other
        }
        do {
            accounts = try await api.activateAccount(id)
        } catch {
            accounts = previous
            throw error
        }
    }

    /// The signed-in account of the same engine `offset` places away, for the arrow keys.
    public func neighbour(of id: String, by offset: Int) -> String? {
        guard let account = account(id) else { return nil }
        let choices = accounts(of: account.provider).filter { $0.signedIn == true || $0.id == id }
        guard let index = choices.firstIndex(where: { $0.id == id }),
            choices.indices.contains(index + offset)
        else { return nil }
        return choices[index + offset].id
    }

    public func remove(_ id: String) async throws {
        busy.insert(id)
        defer { busy.remove(id) }
        accounts = try await api.removeAccount(id)
    }

    /// Asks every signed-in account for its limits now. Too soon after the last ask, it
    /// notes when to try again instead.
    public func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            accounts = try await api.refreshAccounts()
            retryAt = nil
            refreshFailure = nil
        } catch APIError.rateLimited(_, let retryAfter) {
            retryAt = now().addingTimeInterval(TimeInterval(retryAfter ?? 20))
            refreshFailure = nil
        } catch {
            retryAt = nil
            refreshFailure = "Could not refresh"
        }
    }

    /// "Try again in 12 s" while the daemon refuses a refresh, else the last failure.
    public func refreshNote(at date: Date) -> String? {
        if let retryAt, retryAt > date {
            return "Try again in \(Int(retryAt.timeIntervalSince(date).rounded(.up))) s"
        }
        return refreshFailure
    }

    /// The banked resets available on the engine's accounts together.
    public func bankedAvailable(_ provider: String) -> Int {
        accounts(of: provider).reduce(0) { $0 + ($1.bankedResets?.available ?? 0) }
    }

    /// Reads the banked resets of each signed-in account of the engine; an account that
    /// cannot say keeps what it had.
    public func loadBankedResets(_ provider: String) async {
        for account in accounts(of: provider) where account.signedIn == true {
            if let banked = try? await api.bankedResets(account.id) {
                bankedResets[account.id] = banked
            }
        }
    }

    /// Uses a banked reset on the account's limits now, then reads its resets again.
    public func useBankedReset(_ id: String, credit: String) async throws -> BankedResetOutcome {
        let used = try await api.useBankedReset(id, creditID: credit)
        accounts = used.accounts
        if let banked = try? await api.bankedResets(id) {
            bankedResets[id] = banked
        }
        return used.outcome
    }

    /// The Refresh button's words: "as of 14:05" once the shown limits were reported.
    public func refreshTitle(_ groups: [UsageLimitGroup]) -> String {
        UsageText.asOf(reported(groups), calendar: calendar) ?? "Refresh"
    }

    /// The shown limits were last reported more than 10 minutes before `date`.
    public func limitsAreStale(_ groups: [UsageLimitGroup], at date: Date) -> Bool {
        UsageText.isStale(reported(groups), now: date)
    }

    /// When the shown limits were last reported, as a window for the usage words.
    private func reported(_ groups: [UsageLimitGroup]) -> LimitWindow {
        let dates = groups.flatMap { $0.limits?.windows ?? [] }.compactMap(\.updatedAt)
        return LimitWindow(utilization: 0, updatedAt: dates.max())
    }

    public func loadGitHub() async throws {
        github = try await api.githubAccount()
    }

    public func checkGitHub() async throws {
        isCheckingGitHub = true
        defer { isCheckingGitHub = false }
        github = try await api.checkGitHubAccount()
    }

    public func apply(_ event: Event) {
        if case .accountsChanged(let accounts) = event.body {
            self.accounts = accounts
        }
    }

    /// Replaces the account in place, or adds it at the end of its engine's.
    private func put(_ account: EngineAccount) {
        if let index = accounts.firstIndex(where: { $0.id == account.id }) {
            accounts[index] = account
        } else if let last = accounts.lastIndex(where: { $0.provider == account.provider }) {
            accounts.insert(account, at: last + 1)
        } else {
            accounts.append(account)
        }
    }
}
