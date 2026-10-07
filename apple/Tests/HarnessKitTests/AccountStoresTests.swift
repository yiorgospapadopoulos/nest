import Foundation
import Testing

@testable import HarnessKit

private var utc: Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC")!
    return calendar
}

/// 2026-10-06 12:00 UTC, a Tuesday.
private let tuesday = Date(timeIntervalSince1970: 1_791_288_000)

@MainActor
@Suite struct UsageStoreTests {
    let api = FakeAPI()

    func store(now: Date = tuesday) -> UsageStore {
        UsageStore(api: api, calendar: utc, now: { now })
    }

    @Test func loadsLimitsAndTheCurrentMonth() async throws {
        let usage = store()
        #expect(usage.cells.isEmpty)
        #expect(usage.totalTokens == 0)
        #expect(usage.totalSessions == 0)
        #expect(usage.peakDayTokens == 0)

        try await usage.load()

        #expect(usage.limits?.fiveHour?.utilization == 0.3)
        #expect((usage.year, usage.monthNumber) == (2026, 10))
        #expect(usage.totalTokens == 496_000)
        #expect(usage.totalSessions == 12)
        #expect(usage.peakDayTokens == 31_000)
        #expect(api.calls == ["usageLimits", "usageMonth 2026-10"])
    }

    @Test func calendarCellsStartOnMonday() async throws {
        let usage = store()
        try await usage.load()

        let cells = usage.cells
        // October 2026 starts on a Thursday: three blanks for Monday to Wednesday.
        #expect(cells.prefix(3).allSatisfy { $0 == nil })
        let first = try #require(cells[3])
        #expect(first.day == CalendarDay(year: 2026, month: 10, day: 1))
        #expect(first.id == first.day)
        #expect(cells.count == 3 + 31)
        let today = cells.compactMap { $0 }.filter(\.isToday)
        #expect(today.map(\.day.day) == [6])
        #expect(cells.compactMap { $0 }.filter(\.isFuture).count == 25)
        #expect(cells[3 + 3]?.tokens == 0)
        #expect(cells[3 + 1]?.sessions == 3)
    }

    @Test func navigatesMonthsButNotIntoTheFuture() async throws {
        let usage = store()
        try await usage.load()
        #expect(!usage.canShowNextMonth)
        try await usage.showNextMonth()
        #expect(usage.monthNumber == 10)

        try await usage.showPreviousMonth()
        #expect((usage.year, usage.monthNumber) == (2026, 9))
        #expect(usage.canShowNextMonth)
        #expect(usage.month?.month == 9)
        try await usage.showNextMonth()
        #expect(usage.month?.month == 10)
        #expect(api.calls.suffix(2) == ["usageMonth 2026-9", "usageMonth 2026-10"])
    }

    @Test func crossesYearBoundaries() async throws {
        let january = Date(timeIntervalSince1970: 1_768_478_400)  // 2026-01-15
        let usage = store(now: january)
        try await usage.showPreviousMonth()
        #expect((usage.year, usage.monthNumber) == (2025, 12))
        try await usage.showNextMonth()
        #expect((usage.year, usage.monthNumber) == (2026, 1))

        let december = UsageStore(
            api: api, calendar: utc, now: { Date(timeIntervalSince1970: 1_797_379_200) })
        try await december.showPreviousMonth()
        #expect((december.year, december.monthNumber) == (2026, 11))
    }

    @Test func theLastNavigationWins() async throws {
        let usage = store()
        async let first: Void = usage.showPreviousMonth()
        async let second: Void = usage.showPreviousMonth()
        _ = try await (first, second)
        #expect((usage.year, usage.monthNumber) == (2026, 8))
        #expect(usage.month?.month == 8)
    }

    @Test func liveUsageMergesWindows() async throws {
        let usage = store()
        usage.apply(
            Fixture.event(
                EventType.usageUpdated,
                #"{"five_hour": null, "seven_day": {"utilization": 0.06, "resets_at": "2026-10-12T09:00:00Z"}}"#,
                session: nil))
        #expect(usage.limits?.fiveHour == nil)
        #expect(usage.limits?.sevenDay?.updatedAt == Fixture.event("x", "{}").ts)

        usage.apply(
            Fixture.event(
                EventType.usageUpdated,
                #"{"five_hour": {"utilization": 0.4, "resets_at": null}, "seven_day": null}"#,
                session: nil))
        #expect(usage.limits?.fiveHour?.utilization == 0.4)
        #expect(usage.limits?.sevenDay?.utilization == 0.06)

        usage.apply(Fixture.event("daemon.started", "{}"))
        #expect(usage.limits?.fiveHour?.utilization == 0.4)
    }

    @Test func usesTheSystemCalendarByDefault() {
        let usage = UsageStore(api: api)
        let now = Calendar.current.dateComponents([.year, .month], from: Date())
        #expect((usage.year, usage.monthNumber) == (now.year!, now.month!))
    }
}

@MainActor
@Suite struct ConnectorsStoreTests {
    @Test func groupsConnectorsAndCountsTroubles() async throws {
        let api = FakeAPI()
        var odd = Fixture.connectors[2]
        odd.name = "mystery"
        odd.group = .unknown
        let list = Fixture.connectors + [odd]
        api.set { $0.connectors = list }
        let store = ConnectorsStore(api: api)

        try await store.load()

        #expect(store.sections.map(\.id) == [.claudeAI, .claudeCode])
        #expect(
            store.sections.map(\.title) == ["claude.ai connectors", "Plugins and local servers"])
        #expect(
            store.sections[1].connectors.map(\.name)
                == ["plugin:engineering:github", "serena", "mystery"])
        #expect(store.needingAttention == 3)
        #expect(store.sections.map(\.attention) == ["1 needs sign-in", "2 failed"])
        #expect(ConnectorsStore.claudeAISettings.absoluteString.hasSuffix("/settings/connectors"))

        store.apply(
            Fixture.event(
                EventType.connectorsUpdated,
                "{\"connectors\": [\(Fixture.json(Fixture.connectors[1]))]}",
                session: nil))
        #expect(store.sections.map(\.id) == [.claudeCode])
        #expect(store.needingAttention == 0)
        store.apply(Fixture.event("daemon.started", "{}"))
        #expect(store.connectors.count == 1)
    }
}

@Suite struct ConnectorSectionTests {
    func connector(_ status: String) -> Connector {
        var connector = Fixture.connectors[1]
        connector.status = status
        return connector
    }

    @Test func attentionNamesSignInsAndFailuresOnly() {
        func attention(_ statuses: [String]) -> String? {
            ConnectorSection(kind: .claudeCode, connectors: statuses.map(connector)).attention
        }
        #expect(attention(["connected", "pending", "disabled"]) == nil)
        #expect(attention(["needs-auth", "needs_auth", "connected"]) == "2 need sign-in")
        #expect(attention(["failed", "needs-auth"]) == "1 needs sign-in, 1 failed")
        #expect(attention(["failed", "failed"]) == "2 failed")
    }
}

@Suite struct ConnectorStateTests {
    @Test func readsClaudeCodesStatuses() {
        let states = ["connected", "needs-auth", "needs_auth", "failed", "pending", "disabled"]
            .map(ConnectorState.init(status:))
        #expect(
            states == [
                .connected, .needsSignIn, .needsSignIn, .failed, .pending, .other("disabled"),
            ])
        #expect(
            states.map(\.label)
                == ["Connected", "Needs sign-in", "Needs sign-in", "Failed", "Pending", "Disabled"])
        #expect(states.map(\.tone) == [.review, .waiting, .waiting, .failed, .running, .done])
    }

    @Test func claudeAIConnectorsAreManagedThere() {
        let list = Fixture.connectors
        #expect(list.map(\.managedOnClaudeAI) == [true, false, false])
        #expect(list[0].state == .needsSignIn)
        var hinted = list[2]
        hinted.manageHint = .claudeAI
        #expect(hinted.managedOnClaudeAI)
    }
}

@MainActor
@Suite struct DevicesStoreTests {
    let api = FakeAPI()
    let store: DevicesStore

    init() {
        store = DevicesStore(api: api, now: { Date(timeIntervalSince1970: 1_791_288_000) })
    }

    func device(_ id: String, local: Bool = false, seen: Date? = nil) -> Device {
        var device = Fixture.decode([Device].self, "devices")[0]
        device.id = id
        device.name = id
        device.isLocal = local
        device.lastSeenAt = seen
        return device
    }

    @Test func listsActiveDevicesWithThisMacFirst() async throws {
        let phone = device("phone", seen: Date(timeIntervalSince1970: 1_791_288_000 - 300))
        api.set { $0.devices += [phone] }
        try await store.load()
        #expect(store.devices.map(\.id) == ["dev-local", "phone"])
        #expect(store.lastSeenText(store.devices[0]) == "This device")
        #expect(store.lastSeenText(phone) == "Last seen 5m ago")
        #expect(!store.canRevoke(store.devices[0]))
        #expect(store.canRevoke(phone))
        #expect(store.lastSeenText(device("new")) == "Not seen yet")
        #expect(
            store.lastSeenText(device("now", seen: Date(timeIntervalSince1970: 1_791_288_000)))
                == "Last seen now")
    }

    @Test func theClockDefaultsToNow() {
        let live = DevicesStore(api: api)
        #expect(live.lastSeenText(device("phone", seen: Date())) == "Last seen now")
    }

    @Test func revokesADevice() async throws {
        let phone = device("phone")
        api.set { $0.devices = [phone] }
        try await store.load()
        try await store.revoke(phone)
        #expect(store.devices.isEmpty)
        #expect(store.revoking.isEmpty)
        #expect(api.calls.last == "revokeDevice phone")
    }

    @Test func aFailedRevokeKeepsTheDevice() async throws {
        let phone = device("phone")
        api.set { $0.devices = [phone] }
        try await store.load()
        api.fail("revokeDevice")
        await #expect(throws: APIError.self) { try await store.revoke(phone) }
        #expect(store.devices == [phone])
        #expect(store.revoking.isEmpty)
    }

    @Test func pairingCodesCountDown() async throws {
        #expect(store.secondsLeft(at: Date()) == 0)
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["createPairingCode"] = gate.stream }
        let task = Task { try await store.createPairingCode() }
        try await waitFor { store.isCreatingCode }
        gate.continuation.finish()
        try await task.value
        #expect(!store.isCreatingCode)
        #expect(store.pairingCode?.code == "ABCD")
        let expiry = Date(timeIntervalSince1970: 0)
        #expect(store.expiryText(at: expiry.addingTimeInterval(-299.5)) == "Expires in 5:00")
        #expect(store.expiryText(at: expiry.addingTimeInterval(-61)) == "Expires in 1:01")
        #expect(store.expiryText(at: expiry.addingTimeInterval(-9)) == "Expires in 0:09")
        #expect(store.expiryText(at: expiry) == "Expired")
        store.clearPairingCode()
        #expect(store.pairingCode == nil)
    }
}

@MainActor
@Suite struct SettingsStoreTests {
    @Test func startsWithTheDefaults() {
        let settings = SettingsStore(store: MemoryStore())
        #expect(settings.theme == .auto)
        #expect(settings.accent == .graphite)
        #expect(settings.bubble == .accent)
        #expect(settings.glass == DesignTokens.GlassTheme.clear)
        #expect(settings.notifications == NotificationPreferences())
    }

    @Test func persistsNotificationToggles() {
        let memory = MemoryStore()
        let settings = SettingsStore(store: memory)
        settings.notifications.finished = false
        settings.notifications.sound = true
        #expect(memory.values["notifications.finished"] == "off")
        #expect(memory.values["notifications.sound"] == "on")
        #expect(memory.values["notifications.approvals"] == "on")
        let reloaded = SettingsStore(store: memory)
        #expect(!reloaded.notifications.finished)
        #expect(reloaded.notifications.sound)
        #expect(reloaded.notifications.reviews)
    }

    @Test func persistsEveryChoice() {
        let memory = MemoryStore()
        let settings = SettingsStore(store: memory)

        settings.theme = .dark
        settings.accent = .teal
        settings.bubble = .neutral
        settings.glass = DesignTokens.GlassTheme.smoke

        #expect(
            memory.values == [
                "appearance.theme": "dark", "appearance.accent": "teal",
                "appearance.bubble": "neutral", "appearance.glass": "smoke",
            ])
        let reloaded = SettingsStore(store: memory)
        #expect(reloaded.theme == .dark)
        #expect(reloaded.accent == .teal)
        #expect(reloaded.bubble == .neutral)
        #expect(reloaded.glass == DesignTokens.GlassTheme.smoke)
    }

    @Test func everyGlassThemeRoundTrips() {
        let memory = MemoryStore()
        let settings = SettingsStore(store: memory)
        for style in DesignTokens.GlassTheme.all {
            settings.glass = style
            #expect(SettingsStore(store: memory).glass == style)
        }
    }

    @Test func aLeftoverWallpaperIsIgnored() {
        let memory = MemoryStore(["appearance.wallpaper": "sky"])
        let settings = SettingsStore(store: memory)
        settings.glass = DesignTokens.GlassTheme.deep
        #expect(settings.glass == DesignTokens.GlassTheme.deep)
        #expect(memory.values["appearance.wallpaper"] == "sky")
    }

    @Test func invalidStoredValuesFallBack() {
        let settings = SettingsStore(
            store: MemoryStore([
                "appearance.theme": "sepia", "appearance.accent": "purple",
                "appearance.glass": "sand",
            ]))
        #expect(settings.theme == .auto)
        #expect(settings.accent == .graphite)
        #expect(settings.glass == DesignTokens.GlassTheme.clear)
    }

    @Test func defaultsToUserDefaults() {
        #expect(SettingsStore().store is UserDefaultsStore)
    }
}

@Suite struct ThemeTests {
    @Test func themeModeChoosesTheAppearance() {
        #expect(Theme.appearance(for: .auto, system: .dark) == .dark)
        #expect(Theme.appearance(for: .auto, system: .light) == .light)
        #expect(Theme.appearance(for: .light, system: .dark) == .light)
        #expect(Theme.appearance(for: .dark, system: .light) == .dark)
    }

    @Test func everyAccentMapsToItsToken() {
        #expect(
            AccentName.allCases.map { Theme.accent($0).name } == AccentName.allCases.map(\.rawValue)
        )
        #expect(DesignTokens.Accent.all.map(\.name) == AccentName.allCases.map(\.rawValue))
    }

    @Test func accentBubblesUseTheAccent() {
        let theme = Theme.resolve(
            accent: .ocean, bubble: .accent, glass: DesignTokens.GlassTheme.frosted,
            appearance: .dark)
        let ocean = DesignTokens.Accent.ocean
        #expect(theme.appearance == .dark)
        #expect(theme.accent == ocean.fill.dark)
        #expect(theme.onAccent == ocean.on.dark)
        #expect(theme.bubble == ocean.fill.dark)
        #expect(theme.bubbleText == ocean.on.dark)
        #expect(theme.glass == DesignTokens.GlassTheme.frosted)
    }

    @Test func neutralBubblesUseGlassAndPrimaryText() {
        let theme = Theme.resolve(
            accent: .rose, bubble: .neutral, glass: DesignTokens.GlassTheme.clear,
            appearance: .light)
        #expect(theme.bubble == DesignTokens.Colors.Surface.neutralBubble.light)
        #expect(theme.bubbleText == DesignTokens.Colors.Text.primary.light)
        #expect(theme.accent == DesignTokens.Accent.rose.fill.light)
    }

    @MainActor
    @Test func resolvesFromSettings() {
        let settings = SettingsStore(store: MemoryStore())
        settings.theme = .light
        settings.accent = .clay
        settings.glass = DesignTokens.GlassTheme.bluegrey
        let theme = Theme.resolve(settings, system: .dark)
        #expect(
            theme
                == Theme.resolve(
                    accent: .clay, bubble: .accent, glass: DesignTokens.GlassTheme.bluegrey,
                    appearance: .light))
    }

    @Test func statusTonesFollowTheSessionState() {
        #expect(StatusTone.of(.starting, hasReview: false) == .running)
        #expect(StatusTone.of(.running, hasReview: true) == .running)
        #expect(StatusTone.of(.waiting, hasReview: false) == .waiting)
        #expect(StatusTone.of(.failed, hasReview: false) == .failed)
        #expect(StatusTone.of(.interrupted, hasReview: false) == .interrupted)
        #expect(StatusTone.of(.idle, hasReview: true) == .review)
        #expect(StatusTone.of(.idle, hasReview: false) == .done)
        #expect(StatusTone.of(.closed, hasReview: false) == .done)
    }

    @Test func statusTonesUseTheFixedColors() {
        let status = DesignTokens.Status.self
        #expect(
            StatusTone.allCases.map(\.fill) == [
                status.Running.fill, status.Waiting.fill, status.Review.fill, status.Failed.fill,
                status.Interrupted.fill, status.Done.fill,
            ])
        #expect(
            StatusTone.allCases.map(\.text) == [
                status.Running.text, status.Waiting.text, status.Review.text, status.Failed.text,
                status.Interrupted.text, status.Done.text,
            ])
    }
}
