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

    /// A new pixie's request as the settings make it (`PixieSettings.prepared`); the
    /// settings are read first when they were not yet, and a failed read leaves the request
    /// as it is.
    public func prepare(_ request: CreatePixieRequest, openProject: String?) async
        -> CreatePixieRequest
    {
        if settings == nil {
            try? await load()
        }
        return settings?.prepared(request, openProject: openProject) ?? request
    }
}

/// Settings > Accounts: the Claude Code login and the `gh` login (B81).
@MainActor @Observable
public final class AccountsStore {
    public private(set) var claude: ClaudeLogin?
    public private(set) var github: GitHubAccount?
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

    public func apply(_ event: Event) {
        guard case .claudeAccount(let login) = event.body else { return }
        claude = login
        isSigningIn = false
        signInError = login.error
    }
}
