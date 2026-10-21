import Foundation
import Testing

@testable import NestKit

/// B81: the Settings window's models, stores and words.
@Suite struct SettingsModelTests {
    @Test func usageSettingsFromAnOlderDaemonWarnAt80() throws {
        let old = Fixture.decode(UsageSettings.self, json: #"{"refresh_minutes": 5}"#)
        #expect(old == UsageSettings(refreshMinutes: 5, warnPercent: 80, warnNotify: true))
        let off = Fixture.decode(
            UsageSettings.self,
            json: #"{"refresh_minutes": 5, "warn_percent": null, "warn_notify": false}"#)
        #expect(off == UsageSettings(refreshMinutes: 5, warnPercent: nil, warnNotify: false))
        #expect(
            Fixture.json(off) == #"{"refresh_minutes":5,"warn_notify":false,"warn_percent":null}"#)
    }

    @Test func storageSettingsSendNeverAsNull() {
        #expect(Fixture.json(StorageSettings()) == #"{"archive_after_days":null}"#)
        #expect(
            Fixture.decode(StorageSettings.self, json: #"{"archive_after_days": 30}"#)
                == StorageSettings(archiveAfterDays: 30))
        #expect(Fixture.decode(StorageSettings.self, json: "{}") == StorageSettings())
    }

    @Test func pixieSettingsRoundTripWithTheDefaultModelAsNull() {
        let json =
            #"{"autonomy":"observe","habit_usage_percent":80,"habits_paused":false,"max_per_day":5,"max_running":2,"model":null,"project_access":"edit"}"#
        #expect(Fixture.json(PixieSettings()) == json)
        #expect(Fixture.decode(PixieSettings.self, json: json) == PixieSettings())
        let other = Fixture.decode(
            PixieSettings.self,
            json:
                #"{"model":"opus","autonomy":"start","project_access":"none","projects":"all","max_running":3,"max_per_day":10,"report_push":"info","habits_paused":true,"habit_usage_percent":90}"#
        )
        #expect(other.model == "opus")
        #expect(other.projectAccess == .noAccess)
        #expect(other.habitsPaused)
        // B85 moved the report level to the notification rules and dropped projects.
        #expect(!Fixture.json(other).contains("projects"))
        #expect(!Fixture.json(other).contains("report_push"))
    }

    /// The daemon's notification rules (B85): the Mac changes only the pixie report level
    /// and sends the rest back as it read it, since a save replaces the whole section.
    @Test func notificationRulesKeepWhatTheMacDoesNotEdit() {
        let json =
            #"{"kinds": {"pixie_report": true}, "quiet_hours": null, "ntfy": {"enabled": false}, "vapid_subject": "mailto:a@b.c", "pixie_report_level": "warn"}"#
        var rules = Fixture.decode(NotificationRules.self, json: json)
        #expect(rules.pixieReportLevel == .warn)
        rules.pixieReportLevel = .info
        #expect(
            Fixture.json(rules)
                == #"{"kinds":{"pixie_report":true},"ntfy":{"enabled":false},"pixie_report_level":"info","quiet_hours":null,"vapid_subject":"mailto:a@b.c"}"#
        )
        // A daemon from before B85 sends no level: the default, needs action.
        #expect(Fixture.decode(NotificationRules.self, json: "{}").pixieReportLevel == .action)
        #expect(NotificationRules().pixieReportLevel == .action)
        #expect(
            Fixture.decode(NotificationRules.self, json: #"{"pixie_report_level": "loud"}"#)
                .pixieReportLevel == .unknown)
    }

    @Test func accountsAndEventsDecode() {
        let github = Fixture.decode(
            GitHubAccount.self,
            json: #"{"state": "signed_out", "login": null, "checked_at": "2026-10-17T09:00:00Z"}"#)
        #expect(github.state == .signedOut)
        #expect(github.login == nil)
        let warning = Fixture.event(
            EventType.usageWarning,
            #"{"window": "five_hour", "utilization": 0.82, "resets_at": "2026-10-17T18:30:00Z"}"#,
            session: nil)
        #expect(
            warning.body
                == .usageWarning(
                    UsageWarning(
                        window: .fiveHour, utilization: 0.82,
                        resetsAt: Fixture.date("2026-10-17T18:30:00Z"))))
        let login = Fixture.event(
            EventType.accountClaude,
            #"{"signed_in": false, "checked_at": "2026-10-17T09:00:00Z", "error": "cancelled"}"#,
            session: nil)
        #expect(
            login.body
                == .claudeAccount(
                    ClaudeLogin(
                        signedIn: false, checkedAt: Fixture.date("2026-10-17T09:00:00Z"),
                        error: "cancelled")))
        let install = Fixture.event(
            EventType.claudeCodeInstall, #"{"state": "running", "message": "Downloading"}"#,
            session: nil)
        #expect(
            install.body
                == .claudeCodeInstall(
                    ClaudeCodeInstallProgress(state: .running, message: "Downloading")))
        let updated = Fixture.event(
            EventType.claudeCodeUpdated,
            #"{"installed": true, "path": "/usr/local/bin/claude", "version": "2.1.3", "bundled_version": "2.1.0"}"#,
            session: nil)
        #expect(
            updated.body
                == .claudeCodeUpdated(
                    ClaudeCodeStatus(
                        installed: true, path: "/usr/local/bin/claude", version: "2.1.3",
                        bundledVersion: "2.1.0")))
        #expect(
            Fixture.event(EventType.extensionsUpdated, "{}", session: nil).body
                == .extensionsChanged)
    }

    @Test func reposCarryTheirPushAddress() {
        var repo = Fixture.repos[0]
        #expect(repo.remoteURL == nil)
        repo = Fixture.decode(
            Repo.self,
            json:
                #"{"name": "n", "path": "/n", "default_branch": "main", "worktree": {"default": null, "link": [], "setup": [], "setup_timeout_seconds": 900}, "remote_url": "git@github.com:me/n.git"}"#
        )
        #expect(repo.remoteURL == "git@github.com:me/n.git")
    }

    @Test func repoPatchesForBranchRemoteAndTimeout() {
        #expect(RepoPatch(defaultBranch: "dev").isEmpty == false)
        #expect(Fixture.json(RepoPatch(defaultBranch: "dev")) == #"{"default_branch":"dev"}"#)
        #expect(
            Fixture.json(RepoPatch(setupTimeoutSeconds: 300)) == #"{"setup_timeout_seconds":300}"#)
        #expect(Fixture.json(RepoPatch(remoteURL: nil)) == #"{"remote_url":null}"#)
        #expect(
            Fixture.json(RepoPatch(remoteURL: "git@x:y.git")) == #"{"remote_url":"git@x:y.git"}"#)
        #expect(RepoPatch().isEmpty)
    }
}

@Suite struct SettingsTextTests {
    @Test func bytesReadAsFinderCountsThem() {
        #expect(StorageText.bytes(540) == "540 bytes")
        #expect(StorageText.bytes(12_400) == "12 KB")
        #expect(StorageText.bytes(820_000_000) == "820 MB")
        #expect(StorageText.bytes(1_420_000_000) == "1.4 GB")
    }

    @Test func storageShares() {
        let usage = StorageUsage(
            totalBytes: 1_000_000_000, chatsBytes: 500_000_000, attachmentsBytes: 250_000_000,
            artifactsBytes: 0, otherBytes: 250_000_000)
        let shares = StorageText.shares(usage)
        #expect(shares.map(\.part) == StorageText.Part.allCases)
        #expect(shares.map(\.share) == [0.5, 0.25, 0, 0.25])
        #expect(
            StorageText.shares(
                StorageUsage(
                    totalBytes: 0, chatsBytes: 0, attachmentsBytes: 0, artifactsBytes: 0,
                    otherBytes: 0)
            ).isEmpty)
    }

    @Test func ledgerNamesPartsAndSharesInWholePercents() {
        #expect(
            StorageText.Part.allCases.map(\.name) == ["Chats", "Attachments", "Artifacts", "Other"])
        #expect(StorageText.share(0) == "0%")
        #expect(StorageText.share(0.0004) == "<1%")
        #expect(StorageText.share(0.0099) == "<1%")
        #expect(StorageText.share(0.01) == "1%")
        #expect(StorageText.share(0.746) == "75%")
        #expect(StorageText.share(1) == "100%")
        let usage = StorageUsage(
            totalBytes: 18_900_000, chatsBytes: 14_000_000, attachmentsBytes: 1_500_000,
            artifactsBytes: 8_000, otherBytes: 3_392_000)
        let lines = StorageText.ledger(usage)
        #expect(lines.map(\.part) == StorageText.Part.allCases)
        #expect(lines.map(\.size) == ["14 MB", "2 MB", "8 KB", "3 MB"])
        #expect(lines.map(\.share) == ["74%", "8%", "<1%", "18%"])
        let empty = StorageUsage(
            totalBytes: 0, chatsBytes: 0, attachmentsBytes: 0, artifactsBytes: 0, otherBytes: 0)
        #expect(StorageText.ledger(empty).map(\.share) == ["0%", "0%", "0%", "0%"])
    }

    @Test func ledgerSegmentsKeepTinyPartsVisibleAndFillTheWidth() {
        // The zero parts are left out, so one 2 point gap leaves 298 of 300.
        let widths = StorageText.segments(
            [(.chats, 0.75), (.attachments, 0.25), (.artifacts, 0), (.other, 0)], width: 300,
            gap: 2, minimum: 3)
        #expect(widths.map(\.part) == [.chats, .attachments])
        #expect(widths.map(\.width) == [223.5, 74.5])
        let tiny = StorageText.segments(
            [(.chats, 0.999), (.artifacts, 0.001)], width: 102, gap: 2, minimum: 3)
        #expect(tiny.map(\.width) == [97, 3])
        #expect(StorageText.segments([], width: 100, gap: 2, minimum: 3).isEmpty)
    }

    @Test func archiveAndAttachmentWords() {
        #expect(
            StorageText.archiveChoices.map(StorageText.archiveLabel) == [
                "Never", "7 days", "30 days", "90 days",
            ])
        #expect(StorageText.archiveLabel(1) == "1 day")
        func attachment(_ session: String?, _ title: String?) -> LargeAttachment {
            LargeAttachment(
                id: "a", name: "a.png", bytes: 1, mediaType: "image/png", sessionID: session,
                sessionTitle: title, createdAt: Date(timeIntervalSince1970: 0))
        }
        #expect(StorageText.source(of: attachment("s1", "Fix it")) == "Fix it")
        #expect(StorageText.source(of: attachment("s1", nil)) == "Untitled chat")
        #expect(StorageText.source(of: attachment(nil, nil)) == "No chat")
    }

    @Test func pixieChoicesKeepAValueSetElsewhere() {
        #expect(PixieSettingsText.choices([1, 2, 3], including: 2) == [1, 2, 3])
        #expect(PixieSettingsText.choices([1, 2, 5], including: 4) == [1, 2, 4, 5])
        #expect(PixieSettingsText.choices([1, 2], including: nil) == [1, 2])
        #expect(PixieSettingsText.maxRunningChoices == [1, 2, 3, 5])
        #expect(PixieSettingsText.maxPerDayChoices == [3, 5, 10, 20])
        #expect(PixieSettingsText.habitUsageChoices == [70, 80, 90, 100])
    }

    @Test func accountWords() {
        #expect(AccountText.githubState(.signedIn) == "Signed in")
        #expect(AccountText.githubState(.signedOut) == "Signed out")
        #expect(AccountText.githubState(.unavailable) == "gh is not installed")
        #expect(AccountText.githubState(.unknown) == "Unknown")
    }

    @Test func usageWarningWords() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let now = Fixture.date("2026-10-17T12:00:00Z")
        let warning = UsageWarning(
            window: .fiveHour, utilization: 0.816, resetsAt: Fixture.date("2026-10-17T18:30:00Z"))
        #expect(
            UsageText.warning(warning, now: now, calendar: calendar)
                == "You have used 82% of your 5 hour limit. Resets 18:30.")
        let weekly = UsageWarning(window: .sevenDay, utilization: 0.9, resetsAt: nil)
        #expect(
            UsageText.warning(weekly, now: now, calendar: calendar)
                == "You have used 90% of your weekly limit.")
        #expect(UsageText.warnChoices.map(UsageText.warnLevel) == ["70%", "80%", "90%", "Off"])
    }

    @Test func setupTimeouts() {
        #expect(SetupTimeout.choices(including: 900) == [300, 900, 1800])
        #expect(SetupTimeout.choices(including: 60) == [60, 300, 900, 1800])
        #expect(SetupTimeout.label(900) == "15 minutes")
        #expect(SetupTimeout.label(60) == "1 minute")
        #expect(SetupTimeout.label(90) == "90 seconds")
    }

    @Test func usageWarningNotifications() {
        var preferences = NotificationPreferences()
        preferences.sound = true
        let content = NotificationPolicy.content(
            forWarning: "Used 80%", notify: true, preferences: preferences)
        #expect(content?.title == "Usage warning")
        #expect(content?.body == "Used 80%")
        #expect(content?.sessionID == "")
        #expect(content?.playsSound == true)
        #expect(
            NotificationPolicy.content(forWarning: "x", notify: false, preferences: preferences)
                == nil)
        #expect(NotificationPreferences.kindToggles.count == 10)
        #expect(!NotificationPreferences.kindToggles.contains { $0.title == "Sound" })
    }
}

@Suite struct SettingsCatalogTests {
    @Test func pagesHaveTitlesAndSearchFindsRows() {
        #expect(
            SettingsPage.fixed.map(\.title) == [
                "General", "Appearance", "Notifications", "Agents", "Usage", "Storage",
                "Pixies", "Accounts", "Devices", "Keyboard shortcuts", "Configuration",
            ])
        // B97: plugins, marketplaces, skills, MCP servers and connectors live there now.
        for word in ["plugins", "marketplaces", "skills", "mcp servers", "connectors", "hooks"] {
            #expect(SettingsPage.configuration.matches(word))
        }
        #expect(!SettingsPage.accounts.matches("plugins"))
        #expect(SettingsPage.storage.matches("archive"))
        #expect(SettingsPage.storage.matches("search index"))
        #expect(SettingsPage.storage.matches("used by nest"))
        #expect(!SettingsPage.general.matches("archive"))
        #expect(!SettingsPage.general.matches("storage"))
        #expect(SettingsPage.general.matches("show automated chats"))
        #expect(SettingsPage.usage.matches("warn me at"))
        #expect(SettingsPage.usage.matches("weekly"))
        #expect(!SettingsPage.agents.matches("warn me at"))
        #expect(SettingsPage.agents.matches("stuck chats"))
        #expect(SettingsPage.project("nest").title == "nest")
        #expect(SettingsPage.addProject.title == "Add project")
        #expect(SettingsPage.general.matches("  "))
        #expect(SettingsPage.notifications.matches("pixie reports"))
        #expect(SettingsPage.shortcuts.matches("new terminal"))
        #expect(!SettingsPage.devices.matches("grain"))
        for page in SettingsPage.fixed + [.project("x"), .addProject] {
            #expect(!page.labels.isEmpty)
        }
    }

    @Test func listingFiltersPagesAndProjects() {
        let all = SettingsPage.listed(projects: ["nest", "cv"], query: "")
        #expect(all.pages == SettingsPage.fixed)
        #expect(all.projects == [.project("nest"), .project("cv"), .addProject])
        let grain = SettingsPage.listed(projects: ["nest"], query: "grain")
        #expect(grain.pages == [.appearance])
        #expect(grain.projects.isEmpty)
        let named = SettingsPage.listed(projects: ["nest", "cv"], query: "cv")
        #expect(named.projects == [.project("cv")])
        let branch = SettingsPage.listed(projects: ["nest"], query: "default branch")
        #expect(branch.projects == [.project("nest")])
    }

    @Test func pixiesIconIsTheWingedPixie() {
        #expect(
            SettingsPage.pixieGlyph == [
                "............", "....####....", "#..######..#", "##.#.##.#.##", "############",
                "##.######.##", "#..######..#", "....#..#....", "............", "............",
            ])
    }

    @Test func projectTabs() {
        #expect(
            ProjectSettingsTab.tabs(git: true).map(\.rawValue) == [
                "General", "Configuration", "Chats", "Worktrees", "Look", "Artifacts",
            ])
        #expect(SettingsPage.project("x").matches(".mcp.json"))
        #expect(!ProjectSettingsTab.tabs(git: false).contains(.worktrees))
    }
}

@Suite struct ShortcutTests {
    @Test func displaysAsMenusShowThem() {
        #expect(Shortcut("t", [.command, .shift]).display == "⇧⌘T")
        #expect(Shortcut("s", [.command, .control]).display == "⌃⌘S")
        #expect(Shortcut("1", [.command, .option]).display == "⌥⌘1")
        #expect(Shortcut("return").display == "⌘↩")
        #expect(Shortcut(Shortcut.digits).display == "⌘1 … ⌘9")
        #expect(Shortcut(",").display == "⌘,")
    }

    @Test func storedFormRoundTrips() {
        let shortcut = Shortcut("k", [.command, .shift, .option, .control])
        #expect(shortcut.stored == "ctrl+opt+shift+cmd+k")
        #expect(Shortcut(stored: shortcut.stored) == shortcut)
        #expect(Shortcut(stored: "cmd++") == nil)
        #expect(Shortcut(stored: "") == nil)
        #expect(Shortcut(stored: "hyper+k") == nil)
        #expect(Shortcut(stored: "k") == Shortcut("k", []))
    }

    @Test func overlapsIncludeTheProjectDigits() {
        #expect(Shortcut("k").overlaps(Shortcut("k")))
        #expect(!Shortcut("k").overlaps(Shortcut("k", [.command, .shift])))
        #expect(Shortcut(Shortcut.digits).overlaps(Shortcut("3")))
        #expect(Shortcut("3").overlaps(Shortcut(Shortcut.digits)))
        #expect(!Shortcut(Shortcut.digits).overlaps(Shortcut("0")))
        #expect(!Shortcut("a").overlaps(Shortcut("b")))
    }

    @Test func keysAreReadFromCodesOrCharacters() {
        #expect(Shortcut.key(keyCode: 36, characters: "\r") == "return")
        #expect(Shortcut.key(keyCode: 53, characters: nil) == "escape")
        #expect(Shortcut.key(keyCode: 0, characters: "A") == "a")
        #expect(Shortcut.key(keyCode: 56, characters: "") == nil)
        #expect(Shortcut.key(keyCode: 99, characters: " ") == nil)
    }

    @Test func everyCommandHasATitleGroupAndADistinctDefault() {
        let defaults = ShortcutAction.allCases.map(\.defaultShortcut)
        #expect(Set(defaults).count == defaults.count)
        for action in ShortcutAction.allCases {
            #expect(!action.title.isEmpty)
            #expect(action.group.actions.contains(action))
        }
        #expect(ShortcutGroup.allCases.flatMap(\.actions).count == ShortcutAction.allCases.count)
        #expect(ShortcutAction.newTerminal.defaultShortcut.display == "⇧⌘T")
    }

    @Test func theArtifactsViewIsAWindowShortcutNextToBoard() {
        #expect(ShortcutAction.artifacts.title == "Artifacts")
        #expect(ShortcutAction.artifacts.group == .window)
        #expect(ShortcutAction.artifacts.defaultShortcut.display == "⌥⌘3")
    }
}

@MainActor
@Suite struct ShortcutsStoreTests {
    let preferences = MemoryStore()
    var store: ShortcutsStore { ShortcutsStore(store: preferences) }

    @Test func defaultsUntilChangedAndKeptBetweenLaunches() {
        let shortcuts = store
        #expect(shortcuts.shortcut(for: .newChat) == Shortcut("n"))
        #expect(shortcuts.isDefault(.newChat))
        #expect(!shortcuts.hasChanges)
        #expect(shortcuts.set(Shortcut("j", [.command, .shift]), for: .newChat) == .saved)
        #expect(!shortcuts.isDefault(.newChat))
        #expect(preferences.string(forKey: "shortcuts.newChat") == "shift+cmd+j")
        #expect(store.shortcut(for: .newChat) == Shortcut("j", [.command, .shift]))
        // Back to the default forgets the choice.
        #expect(shortcuts.set(Shortcut("n"), for: .newChat) == .saved)
        #expect(shortcuts.isDefault(.newChat))
        #expect(preferences.string(forKey: "shortcuts.newChat") == nil)
    }

    @Test func unreadableStoredValuesAreIgnored() {
        preferences.set("nonsense+x", forKey: "shortcuts.palette")
        #expect(store.shortcut(for: .palette) == Shortcut("k"))
    }

    @Test func refusals() {
        let shortcuts = store
        #expect(shortcuts.set(Shortcut("escape", []), for: .newChat) == .cancelled)
        #expect(shortcuts.set(Shortcut("k"), for: .newChat) == .conflict(.palette))
        #expect(shortcuts.set(Shortcut("q"), for: .newChat) == .reserved)
        #expect(shortcuts.set(Shortcut("j", [.shift]), for: .newChat) == .needsModifier)
        #expect(shortcuts.set(Shortcut("j", []), for: .newChat) == .needsModifier)
        #expect(shortcuts.set(Shortcut("j"), for: .project) == .needsDigit)
        #expect(
            shortcuts.set(Shortcut("1", [.command, .option]), for: .newChat)
                == .conflict(.workspace))
        #expect(shortcuts.set(Shortcut("4"), for: .newChat) == .conflict(.project))
        #expect(shortcuts.isDefault(.newChat))
        #expect(shortcuts.check(Shortcut("n"), for: .newChat) == .saved)
    }

    @Test func refusalMessages() {
        let keys = Shortcut("k")
        #expect(ShortcutChange.saved.message(for: keys) == nil)
        #expect(ShortcutChange.cancelled.message(for: keys) == nil)
        #expect(
            ShortcutChange.conflict(.palette).message(for: keys)
                == "⌘K is already Search chats and commands")
        #expect(ShortcutChange.reserved.message(for: keys) == "⌘K is used by macOS")
        #expect(ShortcutChange.needsModifier.message(for: keys) == "Use ⌘, ⌃ or ⌥ with the key")
        #expect(
            ShortcutChange.needsDigit.message(for: keys)
                == "Press the modifiers with a digit, such as ⌘1")
    }

    @Test func recordingTurnsKeyPressesIntoShortcuts() {
        let shortcuts = store
        let saved = shortcuts.record(
            keyCode: 17, characters: "t", modifiers: [.command, .control], for: .newTerminal)
        #expect(saved?.shortcut == Shortcut("t", [.command, .control]))
        #expect(saved?.change == .saved)
        let digits = shortcuts.record(
            keyCode: 18, characters: "1", modifiers: [.command, .control], for: .project)
        #expect(digits?.shortcut == Shortcut(Shortcut.digits, [.command, .control]))
        #expect(digits?.change == .saved)
        #expect(shortcuts.shortcut(for: .project).display == "⌃⌘1 … ⌃⌘9")
        #expect(
            shortcuts.record(keyCode: 56, characters: "", modifiers: [.shift], for: .newChat)
                == nil)
        let cancel = shortcuts.record(keyCode: 53, characters: nil, modifiers: [], for: .newChat)
        #expect(cancel?.change == .cancelled)
    }

    @Test func restoreDefaultsForgetsEveryChoice() {
        let shortcuts = store
        shortcuts.set(Shortcut("j", [.command, .shift]), for: .newChat)
        shortcuts.set(Shortcut("y", [.command, .shift]), for: .palette)
        #expect(shortcuts.hasChanges)
        shortcuts.restoreDefaults()
        #expect(!shortcuts.hasChanges)
        #expect(preferences.string(forKey: "shortcuts.newChat") == nil)
        #expect(preferences.string(forKey: "shortcuts.palette") == nil)
        #expect(store.shortcut(for: .palette) == Shortcut("k"))
    }
}

@MainActor
@Suite struct B81StoreTests {
    let api = FakeAPI()

    @Test func storageLoadsArchivesAndRestoresARefusal() async throws {
        let store = StorageStore(api: api)
        try await store.load()
        #expect(store.usage?.totalBytes == 1_400)
        #expect(store.settings == StorageSettings())
        try await store.setArchiveAfterDays(30)
        #expect(store.settings?.archiveAfterDays == 30)
        #expect(api.calls.contains("updateStorageSettings 30"))
        api.fail("updateStorageSettings")
        await #expect(throws: APIError.self) { try await store.setArchiveAfterDays(7) }
        #expect(store.settings?.archiveAfterDays == 30)
    }

    @Test func largeAttachmentsAreReviewedAndDeleted() async throws {
        let first = LargeAttachment(
            id: "a1", name: "big.png", bytes: 900, mediaType: "image/png", sessionID: "s1",
            sessionTitle: "Fix", createdAt: Date(timeIntervalSince1970: 0))
        var second = first
        second.id = "a2"
        api.set { $0.largeAttachments = [first, second] }
        let store = StorageStore(api: api)
        try await store.loadAttachments()
        #expect(store.attachments == [first, second])
        #expect(api.calls.contains("largeAttachments 20"))
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["deleteAttachment"] = gate.stream }
        let deleting = Task { try await store.delete(first) }
        try await waitFor { store.deleting.contains("a1") }
        gate.continuation.finish()
        try await deleting.value
        #expect(store.deleting.isEmpty)
        #expect(store.attachments == [second])
        #expect(store.usage?.totalBytes == 1_400)
        // A failed reread keeps the space as it was.
        api.fail("storage")
        try await store.delete(second)
        #expect(store.attachments == [])
        store.closeAttachments()
        #expect(store.attachments == nil)
    }

    @Test func rebuildingTheSearchIndex() async throws {
        let store = StorageStore(api: api)
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["rebuildSearch"] = gate.stream }
        let task = Task { try await store.rebuildSearch() }
        try await waitFor { store.isRebuilding }
        gate.continuation.finish()
        try await task.value
        #expect(!store.isRebuilding)
        #expect(api.calls.contains("rebuildSearch"))
    }

    @Test func pixieSettingsSaveTheWholeSectionAndRestoreARefusal() async throws {
        let store = PixieSettingsStore(api: api)
        try await store.update { $0.maxRunning = 3 }
        #expect(api.calls == ["pixieSettings", "updatePixieSettings"])
        #expect(api.state.withLock { $0.pixieSettings.maxRunning } == 3)
        #expect(store.settings?.maxRunning == 3)
        api.fail("updatePixieSettings")
        await #expect(throws: APIError.self) { try await store.update { $0.habitsPaused = true } }
        #expect(store.settings?.habitsPaused == false)
        api.set { $0.failures = [:] }
        api.fail("pixieSettings")
        let fresh = PixieSettingsStore(api: api)
        await #expect(throws: APIError.self) { try await fresh.update { $0.maxRunning = 1 } }
    }

    @Test func thePixieReportLevelSavesTheWholeRulesAndRestoresARefusal() async throws {
        api.set {
            $0.notificationRules = NotificationRules(fields: ["vapid_subject": .string("x")])
        }
        let store = NotificationRulesStore(api: api)
        #expect(store.rules == nil)
        try await store.setPixieReportLevel(.warn)
        #expect(api.calls == ["notificationRules", "updateNotificationRules warn"])
        #expect(store.rules?.pixieReportLevel == .warn)
        let saved = api.state.withLock { $0.notificationRules }
        #expect(saved.fields["vapid_subject"] == .string("x"))
        api.fail("updateNotificationRules")
        await #expect(throws: APIError.self) { try await store.setPixieReportLevel(.info) }
        #expect(store.rules?.pixieReportLevel == .warn)
        api.set { $0.failures = [:] }
        api.fail("notificationRules")
        let fresh = NotificationRulesStore(api: api)
        await #expect(throws: APIError.self) { try await fresh.setPixieReportLevel(.info) }
        #expect(fresh.rules == nil)
    }

    @Test func githubLoginIsCheckedAgain() async throws {
        let store = AccountsStore(api: api)
        try await store.loadGitHub()
        #expect(store.github?.login == "octo")
        let gate = AsyncStream<Void>.makeStream()
        api.set {
            $0.gates["checkGitHubAccount"] = gate.stream
            $0.github.state = .signedOut
        }
        let task = Task { try await store.checkGitHub() }
        try await waitFor { store.isCheckingGitHub }
        gate.continuation.finish()
        try await task.value
        #expect(!store.isCheckingGitHub)
        #expect(store.github?.state == .signedOut)
    }

    @Test func claudeCodeInstallFollowsItsEvents() async throws {
        let store = ExtensionsStore(api: api)
        try await store.loadClaudeCode()
        #expect(store.claudeCode?.installed == false)
        try await store.installClaudeCode()
        #expect(store.isInstalling)
        store.apply(
            Fixture.event(
                EventType.claudeCodeInstall, #"{"state": "done", "message": null}"#, session: nil))
        #expect(!store.isInstalling)
        #expect(store.install?.state == .done)
        store.apply(
            Fixture.event(
                EventType.claudeCodeUpdated,
                #"{"installed": true, "path": "/p", "version": "2", "bundled_version": "1"}"#,
                session: nil))
        #expect(store.claudeCode?.installed == true)
        store.apply(Fixture.event(EventType.usageUpdated, "{}", session: nil))
        #expect(store.claudeCode?.installed == true)
        api.fail("installClaudeCode")
        await #expect(throws: APIError.self) { try await store.installClaudeCode() }
        #expect(store.install == nil)
    }

    @Test func pushStatusWords() async throws {
        let store = DevicesStore(api: api)
        #expect(store.pushText == "-")
        try await store.loadPushStatus()
        #expect(store.pushText == "On for 1 device")
        api.set { $0.pushDevices = 3 }
        try await store.loadPushStatus()
        #expect(store.pushText == "On for 3 devices")
        api.set { $0.pushDevices = 0 }
        try await store.loadPushStatus()
        #expect(store.pushText == "Off")
    }

    @Test func usageWarningSettingsSaveTheWholeSection() async throws {
        let usage = UsageStore(api: api)
        try await usage.setWarnPercent(nil)
        #expect(api.calls.first == "usageSettings")
        #expect(
            api.state.withLock { $0.usageSettings }
                == UsageSettings(
                    refreshMinutes: 3, warnPercent: nil, warnNotify: true))
        try await usage.setWarnNotify(false)
        #expect(usage.settings?.warnNotify == false)
        #expect(await usage.warningNotifies() == false)
        api.fail("usageSettings")
        let unread = UsageStore(api: api)
        #expect(await unread.warningNotifies() == false)
        await #expect(throws: APIError.self) { try await unread.setWarnNotify(true) }
    }

    @Test func aUsageWarningShowsUntilDismissed() async {
        api.set { $0.usageSettings.warnNotify = true }
        let usage = UsageStore(api: api, now: { Fixture.date("2026-10-17T12:00:00Z") })
        #expect(await usage.warningNotifies())
        usage.apply(
            Fixture.event(
                EventType.usageWarning, #"{"window": "seven_day", "utilization": 0.7}"#,
                session: nil))
        let warning = UsageWarning(window: .sevenDay, utilization: 0.7, resetsAt: nil)
        #expect(usage.warning == warning)
        #expect(usage.warningText(warning) == "You have used 70% of your weekly limit.")
        // Limits arriving later leave the warning alone.
        usage.apply(
            Fixture.event(
                EventType.usageUpdated, #"{"five_hour": {"utilization": 0.1}}"#, session: nil))
        #expect(usage.warning == warning)
        usage.dismissWarning()
        #expect(usage.warning == nil)
    }

    @Test func projectSettingsBeyondTheWorktree() async throws {
        let app = AppStore(api: api, store: MemoryStore())
        try await app.loadRepos()
        let name = Fixture.repos[0].name
        api.set {
            $0.branches[name] = ["main", "dev"]
            // B79's list, counted for this project only.
            $0.artifacts = [
                Fixture.artifact(id: "a1", repo: name), Fixture.artifact(id: "a2", repo: name),
                Fixture.artifact(id: "a3", repo: "elsewhere"),
            ]
        }
        #expect(try await app.branches(of: name) == ["main", "dev"])
        #expect(await app.artifactCount(of: name) == 2)
        api.fail("artifacts", with: APIError.notFound("Not Found"))
        #expect(await app.artifactCount(of: name) == nil)
        try await app.changeRepo(name, RepoPatch(defaultBranch: "dev"))
        #expect(app.repo(name)?.defaultBranch == "dev")
        try await app.changeRepo(name, RepoPatch(remoteURL: "git@x:y.git"))
        #expect(app.repo(name)?.remoteURL == "git@x:y.git")
        try await app.changeRepo(name, RepoPatch(setupTimeoutSeconds: 300))
        #expect(app.repo(name)?.worktree.setupTimeoutSeconds == 300)
    }

    @Test func liveEventsReachTheSettingsStores() async throws {
        let source = ManualEventSource()
        let model = AppModel(api: api, events: source, preferences: MemoryStore())
        var warnings: [UsageWarning] = []
        model.live.onUsageWarning = { warnings.append($0) }
        model.live.route(
            Fixture.event(
                EventType.usageWarning, #"{"window": "five_hour", "utilization": 0.8}"#,
                session: nil))
        #expect(warnings.map(\.utilization) == [0.8])
        model.live.route(
            Fixture.event(
                EventType.accountsChanged, Fixture.json(AccountList(accounts: Fixture.accounts)),
                session: nil))
        #expect(model.accounts.accounts == Fixture.accounts)
        model.live.route(
            Fixture.event(
                EventType.claudeCodeInstall, #"{"state": "failed", "message": "no network"}"#,
                session: nil))
        #expect(model.extensions.install?.message == "no network")
        #expect(model.shortcuts.shortcut(for: .settings) == Shortcut(","))
        #expect(model.storage.usage == nil)
        #expect(model.pixieSettings.settings == nil)
    }
}

@MainActor
@Suite struct ExtensionsStoreTests {
    let api = FakeAPI()

    @Test func installedPluginsSkillsAndMarketplacesLoad() async throws {
        let store = ExtensionsStore(api: api)
        try await store.reloadAll()
        #expect(api.calls.isEmpty)
        try await store.loadInstalled()
        #expect(store.plugins?.map(\.id) == ["pdf@official"])
        #expect(store.skills.map(\.id) == ["/s/notes"])
        #expect(store.marketplaces.map(\.id) == ["official"])
        try await store.loadAvailable()
        #expect(store.available?.map(\.id) == ["pdf@official", "lint@official"])
        try await store.loadDetails("lint@official")
        #expect(store.details["lint@official"]?.source == "x")
    }

    @Test func switchingAPluginOffShowsAtOnceAndPutsItBackWhenRefused() async throws {
        let store = ExtensionsStore(api: api)
        try await store.loadInstalled()
        let plugin = store.plugins![0]
        try await store.setEnabled(plugin, false)
        #expect(store.plugins?[0].enabled == false)
        #expect(api.calls.contains("setPluginEnabled pdf@official false"))
        api.fail("setPluginEnabled", with: APIError.badGateway("cli failed"))
        await #expect(throws: APIError.self) { try await store.setEnabled(plugin, false) }
        #expect(store.plugins?[0].enabled == true)
        #expect(store.busy.isEmpty)
    }

    @Test func installingAndRemovingReadTheListsAgain() async throws {
        let store = ExtensionsStore(api: api)
        try await store.loadInstalled()
        try await store.loadAvailable()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["installPlugin"] = gate.stream }
        let task = Task { try await store.installPlugin("lint@official") }
        try await waitFor { store.busy.contains("lint@official") }
        gate.continuation.finish()
        try await task.value
        #expect(store.plugins?.map(\.id) == ["pdf@official", "lint@official"])
        #expect(api.calls.filter { $0 == "availablePlugins" }.count == 2)
        try await store.uninstallPlugin("pdf@official")
        #expect(store.plugins?.map(\.id) == ["lint@official"])
    }

    @Test func marketplacesAreAddedAndRemoved() async throws {
        let store = ExtensionsStore(api: api)
        try await store.loadInstalled()
        #expect(try await store.addMarketplace("   ") == false)
        #expect(try await store.addMarketplace(" me/plugins ") == true)
        #expect(api.calls.contains("addMarketplace me/plugins"))
        #expect(store.marketplaces.map(\.name) == ["official", "me/plugins"])
        try await store.removeMarketplace("official")
        #expect(store.marketplaces.map(\.name) == ["me/plugins"])
    }

    @Test func anExtensionsEventReadsAgain() async throws {
        let store = ExtensionsStore(api: api)
        try await store.loadInstalled()
        api.set { $0.skills = [] }
        store.apply(Fixture.event(EventType.extensionsUpdated, "{}", session: nil))
        try await waitFor { store.skills.isEmpty }
    }

    @Test func componentSummaries() {
        let details = Fixture.decode(PluginDetails.self, json: RouteCase.detailsJSON)
        #expect(details.components?.summary == ["2 skills", "1 agent", "1 MCP server"])
        let more = PluginComponents(
            skills: PluginComponent(count: 1, names: ["a"]),
            agents: PluginComponent(count: 2, names: ["b", "c"]),
            hooks: PluginComponent(count: 3, names: []),
            mcpServers: PluginComponent(count: 2, names: []),
            lspServers: PluginComponent(count: 1, names: []))
        #expect(
            more.summary == [
                "1 skill", "2 agents", "3 hooks", "2 MCP servers", "1 LSP server",
            ])
        let plugin = Fixture.decode([InstalledPlugin].self, json: RouteCase.pluginsJSON)[0]
        #expect(plugin.description == "PDFs")
        #expect(plugin.scope == "user")
        let available = Fixture.decode([AvailablePlugin].self, json: RouteCase.availableJSON)[0]
        #expect(available.installCount == 12)
    }
}
