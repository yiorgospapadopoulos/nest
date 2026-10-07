import CoreGraphics
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
@Suite struct UsageTextTests {
    func window(_ utilization: Double, resets: Date?) -> LimitWindow {
        LimitWindow(utilization: utilization, resetsAt: resets, updatedAt: nil)
    }

    @Test func percentages() {
        #expect(UsageText.percent(window(0.304, resets: nil)) == "30%")
        #expect(UsageText.percent(nil) == "-")
    }

    @Test func resetTimesReadNaturally() {
        func reset(_ offset: TimeInterval) -> String {
            UsageText.reset(
                window(0.1, resets: tuesday.addingTimeInterval(offset)), now: tuesday,
                calendar: utc)
        }
        #expect(reset(6.5 * 3600) == "Resets 18:30")
        #expect(reset(6 * 24 * 3600 - 3 * 3600) == "Resets Mon 09:00")
        #expect(reset(9 * 24 * 3600) == "Resets 15 Oct")
        #expect(reset(-2 * 24 * 3600) == "Resets 4 Oct")
        #expect(UsageText.reset(nil, now: tuesday, calendar: utc) == "Not reported yet")
        #expect(
            UsageText.reset(window(0.1, resets: nil), now: tuesday, calendar: utc)
                == "Reset time not reported")
    }

    @Test func compactTokens() {
        #expect(
            [940, 1_499, 340_000, 1_200_000, 12_000_000, 999_999].map(UsageText.tokens) == [
                "940", "1k", "340k", "1.2M", "12M", "1M",
            ])
    }

    @Test func monthsAndDays() {
        #expect(UsageText.monthTitle(year: 2026, month: 10) == "October 2026")
        #expect(UsageText.weekdayHeads.first == "Mo")
        let busy = UsageDayCell(
            day: CalendarDay(year: 2026, month: 10, day: 6), tokens: 1_234_567, sessions: 3,
            isToday: true, isFuture: false)
        let detail = UsageText.dayDetail(busy, calendar: utc)
        #expect(detail.title == "Tue 6 Oct")
        #expect(detail.detail == "1,234,567 tokens, 3 sessions")
        let one = UsageDayCell(
            day: busy.day, tokens: 5, sessions: 1, isToday: false, isFuture: false)
        #expect(UsageText.dayDetail(one, calendar: utc).detail == "5 tokens, 1 session")
        let empty = UsageDayCell(
            day: busy.day, tokens: 0, sessions: 0, isToday: false, isFuture: false)
        #expect(UsageText.dayDetail(empty, calendar: utc).detail == "No sessions")
    }

    @Test func shading() {
        #expect(UsageText.shade(tokens: 0, peak: 10) == 0)
        #expect(UsageText.shade(tokens: 5, peak: 0) == 0)
        #expect(abs(UsageText.shade(tokens: 10, peak: 10) - 0.68) < 1e-9)
        #expect(UsageText.isStrong(shade: 0.68))
        #expect(!UsageText.isStrong(shade: 0.3))
    }

    @Test func theStoreUsesItsCalendar() async throws {
        let api = FakeAPI()
        let usage = UsageStore(api: api, calendar: utc, now: { tuesday })
        try await usage.load()
        #expect(usage.monthTitle == "October 2026")
        #expect(usage.resetText(nil) == "Not reported yet")
        let cell = try #require(usage.cells.compactMap { $0 }.first)
        #expect(usage.detail(of: cell).title == "Thu 1 Oct")
    }
}

@MainActor
@Suite struct NotificationPolicyTests {
    func notice(_ kind: NoticeKind, session: String = "s1") -> Notice {
        Notice(kind: kind, sessionID: session, repo: "todo-ui", title: "Dark mode", text: "Done")
    }

    @Test func preferencesChooseKinds() {
        var preferences = NotificationPreferences()
        let kinds: [NoticeKind] = [
            .needsApproval, .question, .reviewReady, .failed, .finished, .unknown,
        ]
        #expect(kinds.map(preferences.wants) == [true, true, true, true, true, false])
        preferences.approvals = false
        preferences.reviews = false
        preferences.errors = false
        preferences.finished = false
        #expect(kinds.allSatisfy { !preferences.wants($0) })
    }

    @Test func buildsTheNotification() {
        var preferences = NotificationPreferences()
        preferences.sound = true
        let content = NotificationPolicy.content(
            for: notice(.reviewReady), preferences: preferences, visibleChats: ["other"])
        #expect(
            content
                == NotificationContent(
                    title: "todo-ui · Dark mode", body: "Done", sessionID: "s1",
                    project: "todo-ui", playsSound: true))
    }

    @Test func skipsVisibleChatsAndSwitchedOffKinds() {
        var preferences = NotificationPreferences()
        #expect(
            NotificationPolicy.content(
                for: notice(.failed), preferences: preferences, visibleChats: ["s1"]) == nil)
        preferences.errors = false
        #expect(
            NotificationPolicy.content(
                for: notice(.failed), preferences: preferences, visibleChats: []) == nil)
    }

    @Test func visibleChatsAreTheFocusedWorkspacesPanes() async throws {
        let api = FakeAPI()
        let app = AppStore(api: api, approvals: ApprovalsStore(api: api), store: MemoryStore())
        #expect(NotificationPolicy.visibleChats(app: app, windowFocused: true).isEmpty)
        try await app.loadRepos()
        let size = CGSize(width: 1200, height: 800)
        app.update { state in
            state.openChat("a", in: size)
            state.openChat("b", in: size)
        }
        #expect(NotificationPolicy.visibleChats(app: app, windowFocused: true) == ["a", "b"])
        #expect(NotificationPolicy.visibleChats(app: app, windowFocused: false).isEmpty)
        app.update { $0.layout.toggleMaximize("b") }
        #expect(NotificationPolicy.visibleChats(app: app, windowFocused: true) == ["b"])
        app.update { $0.view = .board }
        #expect(NotificationPolicy.visibleChats(app: app, windowFocused: true).isEmpty)
    }

    @Test func dockBadge() {
        #expect(NotificationPolicy.badge(pending: 0) == nil)
        #expect(NotificationPolicy.badge(pending: 3) == "3")
    }
}
