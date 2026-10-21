import Foundation
import Testing

@testable import NestKit

/// Accounts as the tests use them (B98): Claude's first account and a profile one, then
/// Codex's first account, signed out.
extension Fixture {
    /// Tue 20 Oct 2026, 10:00 UTC.
    static let accountsNow = Date(timeIntervalSince1970: 1_792_490_400)

    static var utc: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }

    static func limit(
        _ label: String, _ minutes: Int, _ utilization: Double, resetsIn hours: Double?,
        reset: Bool = false
    ) -> AccountLimit {
        AccountLimit(
            label: label, minutes: minutes, utilization: utilization,
            resetsAt: hours.map { accountsNow.addingTimeInterval($0 * 3600) },
            updatedAt: accountsNow.addingTimeInterval(-120), reset: reset)
    }

    static func account(
        _ id: String, _ provider: String = "claude", title: String, name: String? = nil,
        email: String? = nil, plan: String? = nil, signedIn: Bool? = true, active: Bool = false,
        first: Bool = false, signingIn: Bool = false, error: String? = nil,
        limits: [AccountLimit] = [], bankedResets: BankedResets? = nil
    ) -> EngineAccount {
        EngineAccount(
            id: id, provider: provider, name: name, title: title, email: email, plan: plan,
            signedIn: signedIn, active: active, first: first, signingIn: signingIn, error: error,
            limits: limits, bankedResets: bankedResets, checkedAt: accountsNow)
    }

    static var accounts: [EngineAccount] {
        [
            account(
                "claude-main", title: "Personal", name: "Personal", email: "me@example.com",
                plan: "Max 20x", active: true, first: true,
                limits: [
                    limit("5 hour", 300, 0.64, resetsIn: 1.97),
                    limit("Weekly", 10_080, 0.38, resetsIn: 47),
                ]),
            account(
                "a1b2c3d4e5f6", title: "work@example.com", email: "work@example.com", plan: "Pro",
                limits: [
                    limit("5 hour", 300, 0, resetsIn: nil, reset: true),
                    limit("Weekly", 10_080, 0.71, resetsIn: 30),
                ]),
            account(
                "codex-main", "codex", title: "Codex", signedIn: false, active: true, first: true),
        ]
    }
}

@Suite struct EngineAccountModelTests {
    /// The account object as the daemon sends it.
    @Test func decodesTheDaemonsAccount() {
        let json = """
            {"accounts": [{"id": "claude-main", "provider": "claude", "name": "Personal",
              "title": "Personal", "email": "a@b.c", "plan": "Max 20x", "signed_in": true,
              "active": true, "first": true, "signing_in": false, "error": null,
              "limits": [{"label": "5 hour", "minutes": 300, "utilization": 0.64,
                "resets_at": "2026-10-20T12:00:00Z", "updated_at": "2026-10-20T10:00:00Z",
                "reset": false},
                {"label": "Weekly", "minutes": 10080, "utilization": 0, "resets_at": null,
                "updated_at": "2026-10-19T10:00:00Z", "reset": true}],
              "checked_at": null},
              {"id": "codex-main", "provider": "codex", "name": null, "title": "Codex",
              "email": null, "plan": null, "signed_in": null, "active": true, "first": true,
              "signing_in": false, "error": "Access denied", "limits": [], "checked_at": null,
              "banked_resets": {"available": 2, "credits": null}}]}
            """
        let accounts = Fixture.decode(AccountList.self, json: json).accounts
        #expect(accounts.map(\.id) == ["claude-main", "codex-main"])
        let claude = accounts[0]
        #expect(claude.name == "Personal")
        #expect(claude.plan == "Max 20x")
        #expect(claude.signedIn == true)
        #expect(claude.limits.map(\.minutes) == [300, 10_080])
        #expect(claude.limits[1].reset)
        #expect(claude.checkedAt == nil)
        #expect(accounts[1].signedIn == nil)
        #expect(accounts[1].error == "Access denied")
        // Claude has no banked resets; Codex's count comes before their details.
        #expect(claude.bankedResets == nil)
        #expect(accounts[1].bankedResets == BankedResets(available: 2, credits: nil))
    }

    /// A window past its reset counts as 0 used, without a time, in every view.
    @Test func anAccountsWindowsAreUsageLimits() {
        let account = Fixture.accounts[1]
        let windows = try! #require(account.usageLimits?.windows)
        #expect(windows.map(\.label) == ["5 hour", "Weekly"])
        #expect(windows[0].utilization == 0)
        #expect(windows[0].resetsAt == nil)
        #expect(windows[0].reset)
        #expect(windows[1].utilization == 0.71)
        #expect(windows[1].minutes == 10_080)
        #expect(windows[1].updatedAt == Fixture.accountsNow.addingTimeInterval(-120))
        #expect(Fixture.accounts[2].usageLimits == nil)
        let reset = UsageText.reset(windows[0], now: Fixture.accountsNow, calendar: Fixture.utc)
        #expect(reset == "Reset")
    }

    @Test func accountsChangedCarriesTheWholeList() {
        let payload = Fixture.json(AccountList(accounts: Fixture.accounts))
        let event = Fixture.event(EventType.accountsChanged, payload, session: nil)
        guard case .accountsChanged(let accounts) = event.body else {
            Issue.record("not decoded: \(event.body)")
            return
        }
        #expect(accounts == Fixture.accounts)
    }

    /// A rename sends the name, or null to clear it.
    @Test func aRenameSendsNullToClear() {
        #expect(Fixture.json(RenameAccountRequest(name: nil)) == #"{"name":null}"#)
        #expect(Fixture.json(RenameAccountRequest(name: "Work")) == #"{"name":"Work"}"#)
    }
}

@Suite struct AccountTextTests {
    let now = Fixture.accountsNow

    /// The plan, then the email when the title is not already it.
    @Test func aRowsDetailIsThePlanAndTheEmail() {
        let accounts = Fixture.accounts
        #expect(AccountText.detail(accounts[0]) == "Max 20x · me@example.com")
        #expect(AccountText.detail(accounts[1]) == "Pro")
        #expect(AccountText.detail(accounts[2]) == nil)
    }

    @Test func statesAndEngines() {
        let accounts = Fixture.accounts
        #expect(AccountText.state(accounts[0]) == "Signed in")
        #expect(AccountText.state(accounts[2]) == "Signed out")
        var unknown = accounts[2]
        unknown.signedIn = nil
        #expect(AccountText.state(unknown) == "Not checked")
        #expect(AccountText.engine("claude") == "Claude")
        #expect(AccountText.engine("codex") == "Codex")
        #expect(AccountText.engine("gemini") == "Gemini")
    }

    /// The row's two thin lines: the window, its percent and its reset time.
    @Test func compactLimitLines() {
        let lines = Fixture.accounts[0].limits.map {
            AccountText.limitLine($0, now: now, calendar: Fixture.utc)
        }
        #expect(lines == ["5 hour 64% · 11:58", "Weekly 38% · Thu 09:00"])
        let reset = Fixture.accounts[1].limits[0]
        #expect(AccountText.limitLine(reset, now: now, calendar: Fixture.utc) == "5 hour 0%")
        let far = Fixture.limit("30 day", 43_200, 0.04, resetsIn: 24 * 20)
        #expect(AccountText.limitLine(far, now: now, calendar: Fixture.utc) == "30 day 4% · 9 Nov")
        let untimed = Fixture.limit("Weekly", 10_080, 0.5, resetsIn: nil)
        #expect(AccountText.limitLine(untimed, now: now, calendar: Fixture.utc) == "Weekly 50%")
    }
}

@Suite struct BankedResetTextTests {
    let now = Fixture.accountsNow

    /// The Banked resets button counts what is available; each credit says when it expires.
    @Test func bankedResetWords() {
        #expect(AccountText.bankedResetsTitle(0) == "Banked resets")
        #expect(AccountText.bankedResetsTitle(2) == "Banked resets 2")
        let credit = BankedCredit(
            id: "c1", title: nil, description: nil,
            expiresAt: now.addingTimeInterval(20 * 86_400))
        #expect(AccountText.creditTitle(credit) == "Reset")
        #expect(AccountText.creditExpiry(credit, calendar: Fixture.utc) == "expires 9 Nov")
        let named = BankedCredit(id: "c2", title: "Weekly reset", description: "x", expiresAt: nil)
        #expect(AccountText.creditTitle(named) == "Weekly reset")
        #expect(AccountText.creditExpiry(named, calendar: Fixture.utc) == nil)
        #expect(AccountText.useOutcome(.reset) == "Limits reset")
        #expect(AccountText.useOutcome(.nothingToReset) == "Nothing to reset yet")
        #expect(AccountText.useOutcome(.noCredit) == "No banked resets left")
        #expect(AccountText.useOutcome(.alreadyRedeemed) == "That reset was already used")
        #expect(AccountText.useOutcome(.unknown) == "Could not use the reset")
    }
}

@MainActor @Suite struct AccountsStoreTests {
    let api = FakeAPI()

    func loaded() async throws -> AccountsStore {
        api.set { $0.accounts = Fixture.accounts }
        let store = AccountsStore(api: api, calendar: Fixture.utc, now: { Fixture.accountsNow })
        try await store.load()
        return store
    }

    @Test func loadsEveryEnginesAccounts() async throws {
        let store = try await loaded()
        #expect(store.accounts(of: "claude").map(\.id) == ["claude-main", "a1b2c3d4e5f6"])
        #expect(store.accounts(of: "codex").map(\.id) == ["codex-main"])
        #expect(store.account("codex-main")?.title == "Codex")
        #expect(store.account("missing") == nil)
    }

    /// Adding signs in a new account at the end; Codex's answer is a page to open.
    @Test func addingAnAccountSignsItIn() async throws {
        let store = try await loaded()
        let claude = try await store.add("claude")
        #expect(claude == nil)
        #expect(store.accounts(of: "claude").last?.signingIn == true)
        api.set { $0.signInURL = URL(string: "https://auth.openai.com/oauth/authorize?x=1") }
        let codex = try await store.add("codex")
        #expect(codex?.host() == "auth.openai.com")
        #expect(store.accounts(of: "codex").count == 2)
        #expect(api.calls.contains("addAccount claude"))
        #expect(api.calls.contains("addAccount codex"))
        // An engine without accounts yet gets its first at the end.
        let empty = AccountsStore(api: api)
        _ = try await empty.add("gemini")
        #expect(empty.accounts.map(\.provider) == ["gemini"])
    }

    /// Signing in again replaces the row in place; cancelling asks the daemon.
    @Test func signsInAgainAndCancels() async throws {
        let store = try await loaded()
        _ = try await store.signIn("codex-main")
        #expect(store.account("codex-main")?.signingIn == true)
        #expect(store.accounts(of: "codex").count == 1)
        try await store.cancelSignIn("codex-main")
        #expect(api.calls.contains("cancelAccountSignIn codex-main"))
    }

    @Test func signsOutOneAccount() async throws {
        let store = try await loaded()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["signOutAccount"] = gate.stream }
        let out = Task { try await store.signOut("a1b2c3d4e5f6") }
        try await waitFor { store.isBusy("a1b2c3d4e5f6") }
        #expect(!store.isBusy("claude-main"))
        gate.continuation.finish()
        try await out.value
        #expect(!store.isBusy("a1b2c3d4e5f6"))
        #expect(store.account("a1b2c3d4e5f6")?.signedIn == false)
        #expect(store.account("claude-main")?.signedIn == true)
    }

    /// The name is trimmed; an empty one clears it, an unchanged one is not sent.
    @Test func renames() async throws {
        let store = try await loaded()
        // An account without a name shows its email: kept as it is, nothing is sent.
        try await store.rename("a1b2c3d4e5f6", to: "work@example.com")
        #expect(!api.calls.contains { $0.hasPrefix("renameAccount") })
        try await store.rename("a1b2c3d4e5f6", to: "  Work ")
        #expect(store.account("a1b2c3d4e5f6")?.title == "Work")
        #expect(api.calls.last == "renameAccount a1b2c3d4e5f6 Work")
        try await store.rename("a1b2c3d4e5f6", to: "Work")
        #expect(api.calls.last == "renameAccount a1b2c3d4e5f6 Work")
        #expect(api.calls.filter { $0.hasPrefix("renameAccount") }.count == 1)
        try await store.rename("claude-main", to: " ")
        #expect(api.calls.last == "renameAccount claude-main -")
        #expect(store.account("claude-main")?.title == "me@example.com")
        try await store.rename("missing", to: "X")
        #expect(api.calls.last == "renameAccount claude-main -")
    }

    /// The check moves at once and comes back if the daemon refuses; a signed-out or
    /// already active account asks nothing.
    @Test func movesTheCheck() async throws {
        let store = try await loaded()
        try await store.activate("a1b2c3d4e5f6")
        #expect(store.account("a1b2c3d4e5f6")?.active == true)
        #expect(store.account("claude-main")?.active == false)
        #expect(store.account("codex-main")?.active == true)
        let asked = api.calls.count
        try await store.activate("a1b2c3d4e5f6")
        try await store.activate("codex-main")
        try await store.activate("missing")
        #expect(api.calls.count == asked)
        api.set {
            $0.accounts.append(
                Fixture.account("ffffffffffff", "codex", title: "Off", signedIn: false))
        }
        try await store.load()
        let reloaded = api.calls.count
        try await store.activate("ffffffffffff")
        #expect(api.calls.count == reloaded)
        #expect(store.account("ffffffffffff")?.active == false)

        api.fail("activateAccount", with: APIError.conflict("not signed in"))
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["activateAccount"] = gate.stream }
        let moving = Task { try await store.activate("claude-main") }
        try await waitFor { store.account("claude-main")?.active == true }
        #expect(store.account("a1b2c3d4e5f6")?.active == false)
        gate.continuation.finish()
        await #expect(throws: APIError.self) { try await moving.value }
        #expect(store.account("a1b2c3d4e5f6")?.active == true)
        #expect(store.account("claude-main")?.active == false)
    }

    /// The radio group's arrow keys: the next or previous signed-in account of its engine.
    @Test func neighboursAreSignedInAccountsOfTheSameEngine() async throws {
        let store = try await loaded()
        #expect(store.neighbour(of: "claude-main", by: 1) == "a1b2c3d4e5f6")
        #expect(store.neighbour(of: "a1b2c3d4e5f6", by: 1) == nil)
        #expect(store.neighbour(of: "a1b2c3d4e5f6", by: -1) == "claude-main")
        #expect(store.neighbour(of: "claude-main", by: -1) == nil)
        #expect(store.neighbour(of: "codex-main", by: 1) == nil)
        #expect(store.neighbour(of: "missing", by: 1) == nil)
    }

    @Test func removesAProfileAccount() async throws {
        let store = try await loaded()
        try await store.remove("a1b2c3d4e5f6")
        #expect(store.accounts(of: "claude").map(\.id) == ["claude-main"])
        #expect(!store.isBusy("a1b2c3d4e5f6"))
    }

    /// The daemon's word replaces the whole list.
    @Test func eventsReplaceTheList() async throws {
        let store = try await loaded()
        var changed = Fixture.accounts
        changed.removeLast()
        let payload = Fixture.json(AccountList(accounts: changed))
        store.apply(Fixture.event(EventType.accountsChanged, payload, session: nil))
        #expect(store.accounts == changed)
        store.apply(Fixture.event(EventType.reposReordered, "{}", session: nil))
        #expect(store.accounts == changed)
    }

    @Test func refreshReplacesTheLimits() async throws {
        let store = try await loaded()
        var fresher = Fixture.accounts
        fresher[1].limits[1].utilization = 0.9
        api.set { $0.refreshedAccounts = fresher }
        await store.refresh()
        #expect(store.account("a1b2c3d4e5f6")?.limits[1].utilization == 0.9)
        #expect(store.refreshNote(at: Fixture.accountsNow) == nil)
        #expect(!store.isRefreshing)
    }

    @Test func tooSoonCountsDownAndFailuresAreNoted() async throws {
        let store = try await loaded()
        let now = Fixture.accountsNow
        api.fail("refreshAccounts", with: APIError.rateLimited("soon", retryAfter: 12))
        await store.refresh()
        #expect(store.retryAt == now.addingTimeInterval(12))
        #expect(store.refreshNote(at: now) == "Try again in 12 s")
        #expect(store.refreshNote(at: now + 11.5) == "Try again in 1 s")
        #expect(store.refreshNote(at: now + 12) == nil)
        api.fail("refreshAccounts", with: APIError.rateLimited("soon", retryAfter: nil))
        await store.refresh()
        #expect(store.refreshNote(at: now) == "Try again in 20 s")
        api.fail("refreshAccounts")
        await store.refresh()
        #expect(store.refreshNote(at: now) == "Could not refresh")
        #expect(store.retryAt == nil)
        api.set { $0.failures = [:] }
        await store.refresh()
        #expect(store.refreshNote(at: now) == nil)
    }

    @Test func aRefreshUnderWayIsNotRepeated() async throws {
        let store = try await loaded()
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["refreshAccounts"] = gate.stream }
        let first = Task { await store.refresh() }
        try await waitFor { store.isRefreshing }
        await store.refresh()
        gate.continuation.finish()
        await first.value
        #expect(api.calls.filter { $0 == "refreshAccounts" }.count == 1)
    }

    /// The popover's Refresh says when the shown limits were last reported.
    @Test func theRefreshTitleFollowsTheShownLimits() async throws {
        let store = try await loaded()
        let groups = UsageMeter.groups(store.accounts, choice: UsageMeterChoice())
        #expect(store.refreshTitle(groups) == "as of 09:58")
        #expect(!store.limitsAreStale(groups, at: Fixture.accountsNow))
        #expect(store.limitsAreStale(groups, at: Fixture.accountsNow + 10 * 60))
        let quiet = [
            UsageLimitGroup(id: "x", provider: "codex", title: "Codex", active: true, limits: nil)
        ]
        #expect(store.refreshTitle(quiet) == "Refresh")
        #expect(!store.limitsAreStale(quiet, at: Fixture.accountsNow))
    }

    @Test func theClockDefaultsToNow() {
        let store = AccountsStore(api: api)
        #expect(abs(store.now().timeIntervalSinceNow) < 5)
        #expect(store.calendar == .current)
    }
}

@MainActor @Suite struct BankedResetsStoreTests {
    let api = FakeAPI()

    func loaded() async throws -> AccountsStore {
        var accounts = Fixture.accounts
        accounts[2].signedIn = true
        accounts[2].bankedResets = BankedResets(available: 2, credits: nil)
        accounts.append(
            Fixture.account(
                "bbbbbbbbbbbb", "codex", title: "Team", signedIn: false,
                bankedResets: BankedResets(available: 1, credits: nil)))
        api.set {
            $0.accounts = accounts
            $0.banked["codex-main"] = BankedResets(
                available: 2,
                credits: [
                    BankedCredit(id: "r1", title: nil, description: nil, expiresAt: nil),
                    BankedCredit(id: "r2", title: "Bonus", description: nil, expiresAt: nil),
                ])
        }
        let store = AccountsStore(api: api)
        try await store.load()
        return store
    }

    /// The count adds up every account of the engine; Claude has none.
    @Test func countsTheAvailableResets() async throws {
        let store = try await loaded()
        #expect(store.bankedAvailable("codex") == 3)
        #expect(store.bankedAvailable("claude") == 0)
    }

    /// Opening the list reads the details of each signed-in account of the engine.
    @Test func readsTheDetailsOfSignedInAccounts() async throws {
        let store = try await loaded()
        await store.loadBankedResets("codex")
        #expect(api.calls.filter { $0.hasPrefix("bankedResets") } == ["bankedResets codex-main"])
        #expect(store.bankedResets["codex-main"]?.credits?.map(\.id) == ["r1", "r2"])
        #expect(store.bankedResets["bbbbbbbbbbbb"] == nil)
        // An account that cannot say keeps what it had.
        api.fail("bankedResets")
        await store.loadBankedResets("codex")
        #expect(store.bankedResets["codex-main"]?.credits?.count == 2)
    }

    /// Using one answers the outcome, takes the daemon's accounts and reads the credits again.
    @Test func usesABankedReset() async throws {
        let store = try await loaded()
        let outcome = try await store.useBankedReset("codex-main", credit: "r1")
        #expect(outcome == .reset)
        #expect(api.calls.contains("useBankedReset codex-main r1"))
        #expect(store.account("codex-main")?.bankedResets?.available == 1)
        #expect(store.bankedResets["codex-main"]?.credits?.map(\.id) == ["r2"])
        api.set { $0.useOutcome = .nothingToReset }
        #expect(try await store.useBankedReset("codex-main", credit: "r2") == .nothingToReset)
    }

    @Test func outcomesDecodeWithUnknownOnesSafe() {
        let json = #"{"outcome": "no_credit", "accounts": []}"#
        #expect(Fixture.decode(BankedResetUse.self, json: json).outcome == .noCredit)
        let newer = #"{"outcome": "later", "accounts": []}"#
        #expect(Fixture.decode(BankedResetUse.self, json: newer).outcome == .unknown)
        let credit = Fixture.decode(
            BankedResets.self,
            json:
                #"{"available": 1, "credits": [{"id": "r1", "title": null, "description": null, "expires_at": "2026-11-09T10:00:00Z"}]}"#
        )
        #expect(credit.credits?[0].expiresAt == Fixture.date("2026-11-09T10:00:00Z"))
        #expect(Fixture.json(UseBankedResetRequest(creditID: "r1")) == #"{"credit_id":"r1"}"#)
    }
}

@Suite struct UsageMeterTests {
    let now = Fixture.accountsNow

    /// Never chosen: the active account of each engine, following a change of active.
    @Test func theDefaultIsTheActiveAccountOfEachEngine() {
        var accounts = Fixture.accounts
        let entries = UsageMeter.entries(accounts, choice: UsageMeterChoice())
        #expect(entries.map(\.id) == ["claude-main", "a1b2c3d4e5f6", "codex-main"])
        #expect(entries.map(\.shown) == [true, false, true])
        #expect(
            entries.map(\.name) == [
                "Claude · Personal", "Claude · work@example.com", "Codex · Codex",
            ])
        #expect(entries.map(\.detail) == ["Max 20x · in use", "Pro", "Signed out · in use"])
        accounts[0].active = false
        accounts[1].active = true
        let moved = UsageMeter.entries(accounts, choice: UsageMeterChoice())
        #expect(moved.map(\.shown) == [false, true, true])
        // An engine unchecked before B98 starts with its accounts unchecked.
        let migrated = UsageMeter.entries(
            accounts, choice: UsageMeterChoice(hiddenEngines: ["codex"]))
        #expect(migrated.map(\.shown) == [false, true, false])
    }

    /// The user's order first; accounts it does not name follow in the daemon's order.
    @Test func theUsersOrderAndChecks() {
        let choice = UsageMeterChoice(
            order: ["codex-main", "gone", "a1b2c3d4e5f6"], shown: ["a1b2c3d4e5f6"])
        let entries = UsageMeter.entries(Fixture.accounts, choice: choice)
        #expect(entries.map(\.id) == ["codex-main", "a1b2c3d4e5f6", "claude-main"])
        #expect(entries.map(\.shown) == [false, true, false])
    }

    /// One line per checked account that is not signed out, the top two; the title only
    /// when both lines share an engine.
    @Test func theChipShowsTheTopTwoCheckedAccounts() {
        var accounts = Fixture.accounts
        accounts[2].signedIn = true
        accounts.append(Fixture.account("bbbbbbbbbbbb", "codex", title: "Team"))
        let all = UsageMeterChoice(shown: [
            "claude-main", "a1b2c3d4e5f6", "codex-main", "bbbbbbbbbbbb",
        ])
        let lines = UsageMeter.lines(accounts, choice: all, now: now)
        #expect(lines.map(\.id) == ["claude-main", "a1b2c3d4e5f6"])
        #expect(lines.map(\.title) == ["Personal", "work@example.com"])
        #expect(lines.map(\.name) == ["Claude · Personal", "Claude · work@example.com"])
        #expect(lines[0].chip?.entries.map(\.text) == ["64% 1h 58m", "38% 1d 23h"])
        #expect(lines[1].chip?.entries.map(\.text) == ["0% 5h", "71% 1d 6h"])
        let mixed = UsageMeterChoice(
            order: ["codex-main", "claude-main"], shown: ["claude-main", "codex-main"])
        let two = UsageMeter.lines(accounts, choice: mixed, now: now)
        #expect(two.map(\.id) == ["codex-main", "claude-main"])
        #expect(two.map(\.title) == [nil, nil])
        #expect(two[0].chip == nil)
        #expect(two.map(\.provider) == ["codex", "claude"])
        #expect(
            UsageMeter.tooltip(two)
                == "Codex · Codex: not reported yet. Claude · Personal: 5 hour: 64%, resets in 1h 58m. Weekly: 38%, resets in 1d 23h"
        )
    }

    /// Nothing checked and signed in left: the first active account, so the meter stays;
    /// before the accounts load, Claude without numbers.
    @Test func theMeterStays() {
        let none = UsageMeterChoice(shown: ["codex-main"])
        #expect(
            UsageMeter.lines(Fixture.accounts, choice: none, now: now).map(\.id) == ["claude-main"])
        #expect(UsageMeter.groups(Fixture.accounts, choice: none).map(\.id) == ["claude-main"])
        let empty = UsageMeter.lines([], choice: UsageMeterChoice(), now: now)
        #expect(empty.map(\.provider) == ["claude"])
        #expect(empty.map(\.name) == ["Claude"])
        #expect(empty[0].chip == nil)
        let early = UsageMeter.groups([], choice: UsageMeterChoice())
        #expect(early.map(\.title) == ["Claude"])
        // Before Claude reported, its two rows without numbers.
        #expect(early[0].rows.map(\.title) == ["5 hour", "Weekly"])
        #expect(early[0].rows.allSatisfy { $0.window == nil })
    }

    /// Every checked account in the popover, each under "<Engine> · <title>".
    @Test func thePopoverListsEveryCheckedAccount() {
        var accounts = Fixture.accounts
        accounts[2].signedIn = true
        accounts.append(Fixture.account("bbbbbbbbbbbb", "codex", title: "Team"))
        let all = UsageMeterChoice(shown: [
            "claude-main", "a1b2c3d4e5f6", "codex-main", "bbbbbbbbbbbb",
        ])
        let groups = UsageMeter.groups(accounts, choice: all)
        #expect(
            groups.map(\.title) == [
                "Claude · Personal", "Claude · work@example.com", "Codex · Codex", "Codex · Team",
            ])
        #expect(groups.map(\.active) == [true, false, true, false])
        #expect(groups[0].rows.map(\.title) == ["5 hour", "Weekly"])
        // The popover lists the rows by their names.
        #expect(groups[0].rows.map(\.id) == ["5 hour", "Weekly"])
        #expect(groups[2].rows.map(\.title) == ["Usage"])
    }

    /// Drag and Alt plus the arrow keys move a row within the list.
    @Test func reordering() {
        let ids = ["a", "b", "c"]
        #expect(UsageMeter.moved(ids, "a", by: 1) == ["b", "a", "c"])
        #expect(UsageMeter.moved(ids, "c", by: -2) == ["c", "a", "b"])
        #expect(UsageMeter.moved(ids, "a", by: -1) == ids)
        #expect(UsageMeter.moved(ids, "c", by: 5) == ids)
        #expect(UsageMeter.moved(ids, "x", by: 1) == ids)
        #expect(UsageMeter.moved(ids, from: 0, to: 2) == ["b", "c", "a"])
        #expect(UsageMeter.moved(ids, from: 2, to: 0) == ["c", "a", "b"])
    }
}

@MainActor @Suite struct UsageMeterSettingsTests {
    /// The choice is kept on this Mac: the order and, once the user checks or unchecks one,
    /// the checked accounts; the engines unchecked before B98 seed it and are then dropped.
    @Test func theChoiceIsKeptOnThisMac() {
        let store = MemoryStore(["usage.meter.hidden": "codex"])
        let settings = SettingsStore(store: store)
        #expect(settings.usageMeter == UsageMeterChoice(hiddenEngines: ["codex"]))
        let entries = UsageMeter.entries(Fixture.accounts, choice: settings.usageMeter)
        settings.setUsageMeter("a1b2c3d4e5f6", shown: true, entries: entries)
        #expect(settings.usageMeter.shown == ["claude-main", "a1b2c3d4e5f6"])
        #expect(settings.usageMeter.hiddenEngines.isEmpty)
        #expect(store.values["usage.meter.hidden"] == nil)
        #expect(store.values["usage.meter.shown"] == "a1b2c3d4e5f6,claude-main")
        settings.setUsageMeter("claude-main", shown: false, entries: entries)
        settings.setUsageMeter("a1b2c3d4e5f6", shown: false, entries: entries)
        #expect(store.values["usage.meter.shown"] == "")
        settings.orderUsageMeter(["codex-main", "claude-main"])
        #expect(store.values["usage.meter.order"] == "codex-main,claude-main")
        let again = SettingsStore(store: store)
        #expect(
            again.usageMeter == UsageMeterChoice(order: ["codex-main", "claude-main"], shown: []))
        #expect(SettingsStore(store: MemoryStore()).usageMeter == UsageMeterChoice())
    }
}
