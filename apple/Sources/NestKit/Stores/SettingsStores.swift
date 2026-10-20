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

/// Settings > Accounts: the Claude Code login, the Codex login (B94) and the `gh` login
/// (B81).
@MainActor @Observable
public final class AccountsStore {
    public private(set) var claude: ClaudeLogin?
    public private(set) var codex: CodexLogin?
    public private(set) var github: GitHubAccount?
    /// Codex's sign-in waits on the browser until `account.codex` ends it.
    public private(set) var isSigningInCodex = false
    public private(set) var isSigningOutCodex = false
    /// Why the last Codex sign-in failed, as the daemon reported it.
    public private(set) var codexSignInError: String?
    /// Claude Code's sign-in runs on the Mac until `account.claude` ends it.
    public private(set) var isSigningIn = false
    public private(set) var isSigningOut = false
    public private(set) var isCheckingGitHub = false
    /// Why the last sign-in failed, as the daemon reported it.
    public private(set) var signInError: String?

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
    }

    public func loadClaude() async throws {
        claude = try await api.claudeLogin()
    }

    public func loadGitHub() async throws {
        github = try await api.githubAccount()
    }

    public func checkGitHub() async throws {
        isCheckingGitHub = true
        defer { isCheckingGitHub = false }
        github = try await api.checkGitHubAccount()
    }

    /// Starts the browser sign-in; it goes on until the daemon reports the outcome.
    public func signIn() async throws {
        signInError = nil
        isSigningIn = true
        do {
            try await api.signInClaude()
        } catch {
            isSigningIn = false
            throw error
        }
    }

    public func signOut() async throws {
        isSigningOut = true
        defer { isSigningOut = false }
        claude = try await api.signOutClaude()
    }

    public func loadCodex() async throws {
        codex = try await api.codexLogin()
    }

    /// Starts Codex's ChatGPT sign-in and answers the page to open in the browser; it goes
    /// on until the daemon reports the outcome.
    public func signInCodex() async throws -> URL {
        codexSignInError = nil
        isSigningInCodex = true
        do {
            return try await api.signInCodex().authURL
        } catch {
            isSigningInCodex = false
            throw error
        }
    }

    /// Stops the sign-in that waits on the browser; `account.codex` follows.
    public func cancelCodexSignIn() async throws {
        try await api.cancelCodexSignIn()
    }

    public func signOutCodex() async throws {
        isSigningOutCodex = true
        defer { isSigningOutCodex = false }
        codex = try await api.signOutCodex()
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .claudeAccount(let login):
            claude = login
            isSigningIn = false
            signInError = login.error
        case .codexAccount(let login):
            codex = login
            isSigningInCodex = false
            codexSignInError = login.error
        default:
            break
        }
    }
}
