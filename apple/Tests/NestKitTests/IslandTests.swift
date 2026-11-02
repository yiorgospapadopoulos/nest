import Foundation
import Testing

@testable import NestKit

/// Builders for the island's inputs (B114), at minutes after `t0`.
enum Island {
    static let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    static func at(_ minutes: Double) -> Date { t0.addingTimeInterval(minutes * 60) }

    static func pixie(_ id: String, name: String? = nil, chat: String? = nil) -> Pixie {
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie.id = id
        pixie.slug = id
        pixie.name = name ?? id.capitalized
        pixie.chatSessionID = chat
        return pixie
    }

    static func team(_ id: String, name: String, leader: String) -> PixieTeam {
        var team = Fixture.decode(PixieTeam.self, "pixie_team")
        team.id = id
        team.name = name
        team.leaderID = leader
        return team
    }

    static func call(
        _ tool: String, pixie: String = "p1", state: PixieCallState, started: Double,
        finished: Double? = nil
    ) -> ChatPixieCall {
        ChatPixieCall(
            id: "c-\(tool)", pixieID: pixie, toolUseID: tool, agentID: nil, state: state,
            continued: false, startedAt: at(started), finishedAt: finished.map(at))
    }

    static func solo(_ pixie: String, _ calls: ChatPixieCall...) -> ChatPixieEntry {
        ChatPixieEntry(
            kind: .pixie, pixieID: pixie, teamID: nil, state: calls[0].state, members: [],
            calls: calls)
    }

    static func team(_ id: String, leader: String, member: String, _ calls: ChatPixieCall...)
        -> ChatPixieEntry
    {
        ChatPixieEntry(
            kind: .team, pixieID: nil, teamID: id, state: calls[0].state,
            members: [
                ChatTeamMember(pixieID: leader, leader: true, state: calls[0].state),
                ChatTeamMember(pixieID: member, leader: false, state: .running),
            ],
            calls: calls)
    }

    static func approval(
        _ id: String, session: String = "s1", kind: ApprovalKind = .permission,
        call: String? = nil, created: Double, repo: String = "todo-ui"
    ) -> Approval {
        var payload: [String: JSONValue] = [
            "tool": .string("Bash"), "input": .object(["command": .string("npm install")]),
        ]
        if let call { payload["call"] = .string(call) }
        return Approval(
            id: id, sessionID: session, repo: repo, title: "A chat", kind: kind,
            status: .pending, payload: .object(payload), resolution: nil,
            createdAt: at(created), resolvedAt: nil)
    }

    static func agent(
        _ id: String, parent: String? = nil, activity: String? = nil, description: String? = nil,
        started: Double = 0
    ) -> TrackedAgent {
        TrackedAgent(
            id: id, name: "agent", description: description, parent: parent, status: .running,
            activity: activity, startedAt: at(started), finishedAt: nil, steps: [])
    }

    static func run(
        _ session: String, pixie: String = "p1", outcome: HabitRunOutcome, started: Double,
        ended: Double? = nil
    ) -> HabitRun {
        HabitRun(
            id: "r-\(session)", habitID: "h-\(session)", pixieID: pixie, sessionID: session,
            dueAt: at(started), startedAt: at(started), endedAt: ended.map(at), outcome: outcome,
            reason: nil, reportTitle: nil)
    }

    static func chat(
        _ id: String, repo: String = "todo-ui", working: Bool = false, updated: Double = 0,
        normal: Bool = true
    ) -> IslandChat {
        IslandChat(id: id, repo: repo, working: working, updatedAt: at(updated), isNormal: normal)
    }

    static let pixies = [pixie("p1", name: "Brook"), pixie("p2", name: "Moth"), pixie("p3")]

    static func snapshot(
        groups: [String: [ChatPixieEntry]] = [:], agents: [String: [TrackedAgent]] = [:],
        approvals: [Approval] = [], runs: [HabitRun] = [], chats: [IslandChat] = [],
        seen: [String: Date] = [:], order: IslandOrder = .newestFirst, now: Double = 10,
        fullScreen: Bool = false, pill: Bool = false, pixies: [Pixie] = Island.pixies,
        teams: [PixieTeam] = [], awake: Double? = nil
    ) -> IslandSnapshot {
        IslandSnapshot(
            groups: groups, agents: agents, approvals: approvals, habitRuns: runs, pixies: pixies,
            teams: teams,
            chats: Dictionary(uniqueKeysWithValues: chats.map { ($0.id, $0) }), seen: seen,
            installedAt: t0, order: order, now: at(now), fullScreen: fullScreen, pill: pill,
            awakeSince: awake.map(at))
    }
}

@Suite struct IslandStateTests {
    typealias I = Island

    /// A running call works on the left, its row saying what it does right now: its live
    /// activity, else its description, else "Working".
    @Test func workingPixiesShowOnTheLeftWithWhatTheyDo() {
        let state = IslandState.make(
            I.snapshot(
                groups: [
                    "s1": [
                        I.solo("p1", I.call("tu1", state: .running, started: 1)),
                        I.solo("p2", I.call("tu2", pixie: "p2", state: .running, started: 2)),
                        I.solo("p3", I.call("tu3", pixie: "p3", state: .running, started: 3)),
                    ]
                ],
                agents: [
                    "s1": [
                        I.agent("tu1", activity: "Editing auth.ts"),
                        I.agent("tu2", description: "Fix the parser"),
                    ]
                ],
                chats: [I.chat("s1", working: true)]))

        #expect(state.left.map(\.id) == ["s1/pixie:p3", "s1/pixie:p2", "s1/pixie:p1"])
        #expect(state.left.map(\.activity) == ["Working", "Fix the parser", "Editing auth.ts"])
        #expect(state.left.allSatisfy { $0.status == .working })
        #expect(state.left[2].label == "Brook")
        #expect(state.left[2].place == .chat(session: "s1", repo: "todo-ui"))
        #expect(state.right.isEmpty)
        #expect(state.nightshade == nil)
        #expect(state.workingChats == ["s1"])
    }

    /// An approval raised inside a call names it; a team member's names its leader's call,
    /// so the team needs the user. A normal chat's approval (no call) never shows.
    @Test func anApprovalNamingTheCallMakesItNeedYou() throws {
        let pixies = I.pixies
        let team = I.team("t1", name: "Docs team", leader: "p2")
        let state = IslandState.make(
            I.snapshot(
                groups: [
                    "s1": [
                        I.solo("p1", I.call("tu1", state: .running, started: 1)),
                        I.team(
                            "t1", leader: "p2", member: "p3",
                            I.call("tu-lead", pixie: "p2", state: .running, started: 2)),
                    ]
                ],
                agents: [
                    "s1": [
                        I.agent("tu-lead", activity: "Planning"),
                        I.agent("tu-member", parent: "tu-lead", activity: "Rewriting the README"),
                    ]
                ],
                approvals: [
                    I.approval("a1", call: "tu-lead", created: 4),
                    I.approval("a2", session: "s2", created: 5),
                ],
                chats: [I.chat("s1", working: true), I.chat("s2", working: true)],
                pixies: pixies, teams: [team]))

        #expect(state.left.map(\.id) == ["s1/pixie:p1"])
        let needs = try #require(state.right.first)
        #expect(state.right.count == 1)
        #expect(needs.id == "s1/team:t1")
        #expect(needs.status == .needsYou)
        #expect(needs.approvalID == "a1")
        #expect(needs.label == "Docs team")
        #expect(needs.since == I.at(4))
        #expect(needs.activity == "Permission · Bash npm install")
        guard case .team(let shown, _, let cells) = needs.figure else {
            Issue.record("a team shows its icon")
            return
        }
        #expect(shown.id == "t1")
        #expect(cells.count == 4)
    }

    @Test func aWorkingTeamSaysWhatItsNewestRunningMemberDoes() {
        let state = IslandState.make(
            I.snapshot(
                groups: [
                    "s1": [
                        I.team(
                            "t1", leader: "p2", member: "p3",
                            I.call("tu-lead", pixie: "p2", state: .running, started: 2))
                    ]
                ],
                agents: [
                    "s1": [
                        I.agent("tu-lead", activity: "Planning"),
                        I.agent("m1", parent: "tu-lead", activity: "Reading", started: 3),
                        I.agent("m2", parent: "m1", activity: "Rewriting the README", started: 4),
                        I.agent("other", activity: "Elsewhere", started: 5),
                    ]
                ],
                teams: [I.team("t1", name: "Docs team", leader: "p2")]))
        #expect(state.left.map(\.activity) == ["Rewriting the README"])
    }

    /// Opening the chat after the approval came turns it calm, keeping when it was seen; a
    /// newer approval makes it need the user again.
    @Test func aSeenMarkCalmsNeedsYouUntilANewerApproval() {
        let groups = ["s1": [I.solo("p1", I.call("tu1", state: .running, started: 1))]]
        let calm = IslandState.make(
            I.snapshot(
                groups: groups, approvals: [I.approval("a1", call: "tu1", created: 2)],
                seen: ["s1": I.at(3)]))
        #expect(calm.right.map(\.status) == [.seen])
        #expect(calm.right[0].since == I.at(3))
        #expect(calm.right[0].approvalID == "a1")
        #expect(calm.nightshade == .idle)

        let again = IslandState.make(
            I.snapshot(
                groups: groups,
                approvals: [
                    I.approval("a1", call: "tu1", created: 2),
                    I.approval("a2", call: "tu1", created: 4),
                ],
                seen: ["s1": I.at(3)]))
        #expect(again.right.map(\.status) == [.needsYou])
        #expect(again.right[0].approvalID == "a2")
    }

    /// A finished call shows until its chat is seen; one that finished before the island was
    /// first shown never shows. Failed and interrupted ones show the same way.
    @Test func finishedCallsShowUntilSeenAndNeverFromBeforeTheInstall() {
        let groups = [
            "s1": [
                I.solo("p1", I.call("tu1", state: .done, started: 1, finished: 5)),
                I.solo("p2", I.call("tu2", pixie: "p2", state: .failed, started: 1, finished: 4)),
            ],
            "s2": [
                I.solo(
                    "p3", I.call("tu3", pixie: "p3", state: .interrupted, started: 1, finished: 3)),
                I.solo("p1", I.call("old", state: .done, started: -9, finished: -1)),
            ],
        ]
        let fresh = IslandState.make(I.snapshot(groups: groups))
        #expect(fresh.right.map(\.id) == ["s1/pixie:p1", "s1/pixie:p2", "s2/pixie:p3"])
        #expect(fresh.right.map(\.status) == [.done, .failed, .interrupted])
        #expect(fresh.right.map(\.activity) == ["Finished", "Failed", "Interrupted"])
        #expect(fresh.right.map(\.word) == ["Done", "Failed", "Interrupted"])
        #expect(fresh.right[0].since == I.at(5))

        let seen = IslandState.make(I.snapshot(groups: groups, seen: ["s1": I.at(6)]))
        #expect(seen.right.map(\.id) == ["s2/pixie:p3"])

        // Finished after the chat was seen: it shows again.
        let later = IslandState.make(I.snapshot(groups: groups, seen: ["s1": I.at(4.5)]))
        #expect(later.right.map(\.id) == ["s1/pixie:p1", "s2/pixie:p3"])
    }

    /// Chats without a pixie (and a pixie's own chat when the user talks to it) only make
    /// Nightshade hop; a habit run's session is not one. Nightshade sleeps after two quiet
    /// minutes.
    @Test func normalChatsOnlyMoveNightshadeWhichSleepsAfterTwoMinutes() {
        let working = IslandState.make(
            I.snapshot(chats: [I.chat("s1", working: true)], now: 10))
        #expect(working.nightshade == .working)
        #expect(working.left.isEmpty && working.right.isEmpty)

        let habit = IslandState.make(
            I.snapshot(chats: [I.chat("hs", working: true, updated: 0, normal: false)], now: 10))
        #expect(habit.nightshade == .asleep)

        let justStopped = IslandState.make(I.snapshot(chats: [I.chat("s1", updated: 8.1)], now: 10))
        #expect(justStopped.nightshade == .idle)
        let quiet = IslandState.make(I.snapshot(chats: [I.chat("s1", updated: 7.9)], now: 10))
        #expect(quiet.nightshade == .asleep)

        // A freshly started island is awake for two minutes, then sleeps.
        #expect(IslandState.make(I.snapshot(now: 10, awake: 8.1)).nightshade == .idle)
        #expect(IslandState.make(I.snapshot(now: 10, awake: 7.9)).nightshade == .asleep)

        let callEnded = IslandState.make(
            I.snapshot(
                groups: [
                    "s1": [I.solo("p1", I.call("tu1", state: .done, started: 1, finished: 9))]
                ],
                seen: ["s1": I.at(9.5)], now: 10))
        #expect(callEnded.nightshade == .idle)
        #expect(callEnded.list.isEmpty)
    }

    /// Working pixies sort by start, finished ones by finish, needs you by the approval;
    /// oldest first reverses it and equal times go by id.
    @Test func entriesOrderNewestOrOldestFirst() {
        let groups = [
            "s1": [
                I.solo("p1", I.call("tu1", state: .running, started: 1)),
                I.solo("p2", I.call("tu2", pixie: "p2", state: .running, started: 3)),
                I.solo("p3", I.call("tu3", pixie: "p3", state: .done, started: 0, finished: 2)),
            ],
            "s2": [I.solo("p1", I.call("tu4", state: .running, started: 3))],
        ]
        let approvals = [I.approval("a1", session: "s2", call: "tu4", created: 6)]
        let newest = IslandState.make(I.snapshot(groups: groups, approvals: approvals))
        #expect(
            newest.list.map(\.id) == ["s2/pixie:p1", "s1/pixie:p2", "s1/pixie:p3", "s1/pixie:p1"])
        #expect(newest.left.map(\.id) == ["s1/pixie:p2", "s1/pixie:p1"])
        #expect(newest.right.map(\.id) == ["s2/pixie:p1", "s1/pixie:p3"])

        let oldest = IslandState.make(
            I.snapshot(groups: groups, approvals: approvals, order: .oldestFirst))
        #expect(
            oldest.list.map(\.id) == ["s1/pixie:p1", "s1/pixie:p3", "s1/pixie:p2", "s2/pixie:p1"])

        let tied = IslandState.make(
            I.snapshot(groups: [
                "s1": [
                    I.solo("p2", I.call("tu2", pixie: "p2", state: .running, started: 1)),
                    I.solo("p1", I.call("tu1", state: .running, started: 1)),
                ]
            ]))
        #expect(tied.left.map(\.id) == ["s1/pixie:p1", "s1/pixie:p2"])
    }

    /// In full screen only what needs the user shows, on the right; with nothing the island
    /// and its hover target are gone. Turned off, nothing shows.
    @Test func fullScreenShowsOnlyNeedsYouAndOffShowsNothing() {
        let groups = [
            "s1": [
                I.solo("p1", I.call("tu1", state: .running, started: 1)),
                I.solo("p2", I.call("tu2", pixie: "p2", state: .done, started: 1, finished: 2)),
                I.solo("p3", I.call("tu3", pixie: "p3", state: .running, started: 1)),
            ]
        ]
        let approvals = [I.approval("a1", call: "tu3", created: 3)]
        let full = IslandState.make(
            I.snapshot(groups: groups, approvals: approvals, fullScreen: true))
        #expect(full.left.isEmpty)
        #expect(full.nightshade == nil)
        #expect(full.right.map(\.id) == ["s1/pixie:p3"])
        #expect(!full.isHidden)
        #expect(full.list.count == 3)

        let nothing = IslandState.make(I.snapshot(groups: groups, fullScreen: true))
        #expect(nothing.isHidden)

        var off = I.snapshot(groups: groups, approvals: approvals)
        off.shown = false
        #expect(IslandState.make(off) == .empty)
    }

    @Test func thePillRestsBluebellOnlyWhileNothingShows() {
        let empty = IslandState.make(I.snapshot(pill: true))
        #expect(empty.restingBluebell)
        #expect(empty.nightshade == .asleep)

        let busy = IslandState.make(
            I.snapshot(
                groups: ["s1": [I.solo("p1", I.call("tu1", state: .running, started: 1))]],
                pill: true))
        #expect(!busy.restingBluebell)
        #expect(!IslandState.make(I.snapshot()).restingBluebell)
    }

    /// A habit run shows like a called pixie and opens its own session; any blocking approval
    /// in that session makes it need the user. A queued run never shows.
    @Test func habitRunsShowLikeCalledPixies() {
        let running = I.run("hs1", outcome: .running, started: 1)
        let state = IslandState.make(
            I.snapshot(
                agents: ["hs1": [I.agent("main", activity: "Checking pull requests")]],
                runs: [running, I.run("hs2", pixie: "p2", outcome: .queued, started: 2)]))
        #expect(state.left.map(\.id) == ["habit:hs1"])
        #expect(state.left[0].place == .habitRun(session: "hs1"))
        #expect(state.left[0].activity == "Checking pull requests")
        #expect(state.left[0].label == "Brook")

        let asking = IslandState.make(
            I.snapshot(
                approvals: [
                    I.approval("a1", session: "hs1", kind: .question, created: 3),
                    I.approval("a2", session: "hs1", kind: .review, created: 4),
                ],
                runs: [running]))
        #expect(asking.right.map(\.status) == [.needsYou])
        #expect(asking.right[0].approvalID == "a1")

        let ended = IslandState.make(
            I.snapshot(runs: [
                I.run("hs1", outcome: .reported, started: 1, ended: 4),
                I.run("hs2", pixie: "p2", outcome: .timedOut, started: 1, ended: 5),
            ]))
        #expect(ended.right.map(\.status) == [.failed, .done])
    }

    /// A call made in a pixie's own chat opens that pixie's chat.
    @Test func callsInAPixiesOwnChatOpenThatChat() {
        let pixies = [I.pixie("p1", name: "Brook", chat: "pc1"), I.pixie("p2")]
        let state = IslandState.make(
            I.snapshot(
                groups: [
                    "pc1": [I.solo("p2", I.call("tu1", pixie: "p2", state: .running, started: 1))]
                ],
                pixies: pixies))
        #expect(state.left.map(\.place) == [.pixieChat(pixie: "p1", session: "pc1")])
    }
}

extension IslandEntry {
    var word: String { status.word }
}

@Suite struct IslandLayoutTests {
    typealias L = IslandLayout

    /// Up to three show; the +N sits beside them while it fits, else on top of the first;
    /// at least one always shows.
    @Test func aSideShowsWhatFits() {
        #expect(L.count(space: 1000, entries: 5) == (3, true))
        #expect(L.count(space: 1000, entries: 3) == (3, false))
        #expect(L.count(space: 96, entries: 5) == (2, true))
        #expect(L.count(space: 95, entries: 5) == (1, true))
        #expect(L.count(space: L.smallest, entries: 5) == (1, false))
        #expect(L.count(space: L.smallest, entries: 1) == (1, false))
        #expect(L.count(space: 0, entries: 0) == (0, false))
    }

    @Test func freeWidthComesFromTheMenusAndIsSmallestWithoutAccessibility() {
        let free = L.freeWidth(
            notchMinX: 600, notchMaxX: 800, appMenuMaxX: 400, statusItemMinX: 1000)
        #expect(free.left == 190)
        #expect(free.right == 190)
        let blind = L.freeWidth(
            notchMinX: 600, notchMaxX: 800, appMenuMaxX: nil, statusItemMinX: nil)
        #expect(blind.left == L.smallest)
        #expect(blind.right == L.smallest)
    }

    private func entries(_ statuses: [IslandStatus]) -> [IslandEntry] {
        statuses.enumerated().map { index, status in
            IslandEntry(
                id: "e\(index)", figure: .pixie(Island.pixie("p1")), label: "Brook",
                place: .chat(session: "s1", repo: "todo-ui"), approvalID: nil, status: status,
                since: Island.t0, activity: "")
        }
    }

    /// The +N turns orange when one it hides needs the user, not for a hidden done one.
    @Test func wingsGrowAndTheCountWarnsOfWhatItHides() {
        var state = IslandState.make(Island.snapshot())
        state.right = entries([.done, .done, .done, .needsYou])
        let roomy = L.fit(state, left: 1000, right: 1000, pill: false)
        #expect(
            roomy.left
                == IslandSideFit(
                    shown: 1, more: 0, countInline: false, moreIsAlert: false, width: 40))
        #expect(roomy.right.shown == 3)
        #expect(roomy.right.more == 1)
        #expect(roomy.right.countInline)
        #expect(roomy.right.moreIsAlert)
        #expect(roomy.right.width == 8 + 90 + 24 + 6)

        state.right = entries([.needsYou, .done, .done, .done])
        let tight = L.fit(state, left: L.smallest, right: L.smallest, pill: false)
        #expect(tight.right.shown == 1)
        #expect(tight.right.more == 3)
        #expect(!tight.right.countInline)
        #expect(!tight.right.moreIsAlert)
        #expect(tight.right.width == 8 + 30 + 6)
    }

    @Test func thePillKeepsBothSidesEven() {
        let empty = L.fit(
            IslandState.make(Island.snapshot(pill: true)), left: 0, right: 0, pill: true)
        #expect(empty.left.width == 76)
        #expect(empty.right.width == 76)
        #expect(empty.right.shown == 1)

        var state = IslandState.make(Island.snapshot(pill: true))
        state.restingBluebell = false
        state.right = entries([.done, .done, .done])
        let busy = L.fit(state, left: 0, right: 0, pill: true)
        #expect(busy.right.shown == 3)
        #expect(busy.left.width == 104)
        #expect(busy.right.width == 104)
    }
}

@Suite struct IslandClickTests {
    private func entry(_ status: IslandStatus, approval: String? = nil) -> IslandEntry {
        IslandEntry(
            id: "s1/pixie:p1", figure: .pixie(Island.pixie("p1")), label: "Brook",
            place: .chat(session: "s1", repo: "todo-ui"), approvalID: approval, status: status,
            since: Island.t0, activity: "")
    }

    @Test func clicksOpenNestTheChatOrTheList() {
        let place = IslandPlace.chat(session: "s1", repo: "todo-ui")
        #expect(IslandAction.of(.strip) == .openNest)
        #expect(IslandAction.of(.more) == .showList)
        #expect(IslandAction.of(.entry(entry(.working))) == .open(place))
        #expect(IslandAction.of(.entry(entry(.done))) == .open(place))
        #expect(
            IslandAction.of(.entry(entry(.needsYou, approval: "a1")))
                == .openApproval(place, approvalID: "a1"))
        #expect(IslandAction.of(.entry(entry(.seen, approval: "a1"))).seenChat == "s1")
        #expect(IslandAction.openNest.seenChat == nil)
    }
}

@MainActor @Suite struct IslandStoreTests {
    typealias I = Island

    final class Clock: @unchecked Sendable {
        var now = Island.at(0)
    }

    private func model(_ api: FakeAPI, prefs: MemoryStore, clock: Clock) -> AppModel {
        AppModel(
            api: api, events: ManualEventSource(), preferences: prefs, now: { clock.now })
    }

    private func setUp(_ api: FakeAPI) {
        api.set {
            $0.pixies = Island.pixies
            $0.sessions = [Fixture.session("s1", state: .running)]
            $0.pixieGroups = [
                "s1": [
                    I.solo("p1", I.call("tu1", state: .running, started: 1)),
                    I.solo("p2", I.call("tu2", pixie: "p2", state: .done, started: 1, finished: 2)),
                ]
            ]
            $0.approvals = [I.approval("a1", call: "tu1", created: 3)]
        }
    }

    /// Clicking a pixie opens its chat and marks it seen: the done one leaves, the one that
    /// needs the user turns calm. The marks, the install time and the settings outlive the
    /// app.
    @Test func clicksMarkTheChatSeenAndTheMarksPersist() async throws {
        let api = FakeAPI()
        setUp(api)
        let prefs = MemoryStore()
        let clock = Clock()
        let model = model(api, prefs: prefs, clock: clock)
        await model.live.refresh()
        clock.now = I.at(5)

        let before = model.island.state()
        #expect(before.right.map(\.status) == [.needsYou, .done])
        let action = model.island.click(.entry(before.right[0]))
        #expect(action == .openApproval(.chat(session: "s1", repo: "todo-ui"), approvalID: "a1"))
        #expect(model.island.state().right.map(\.status) == [.seen])

        model.island.order = .oldestFirst
        model.island.shown = false
        clock.now = I.at(60)
        let again = self.model(api, prefs: prefs, clock: clock)
        await again.live.refresh()
        #expect(again.island.installedAt == I.at(0))
        #expect(again.island.order == .oldestFirst)
        #expect(!again.island.shown)
        again.island.shown = true
        #expect(again.island.state().right.map(\.status) == [.seen])
    }

    /// Opening the chat in Nest by any route counts as clicking its pixies.
    @Test func openingAChatMarksItSeen() async {
        let api = FakeAPI()
        setUp(api)
        let clock = Clock()
        let model = model(api, prefs: MemoryStore(), clock: clock)
        await model.live.refresh()
        clock.now = I.at(5)

        model.island.markSeen(chat: "s1")
        #expect(model.island.state().right.map(\.status) == [.seen])
        #expect(model.island.state().left.isEmpty)
    }

    /// Running habit runs come from each pixie's habits at connect, then from events.
    @Test func habitRunsAreReadAtConnectAndFollowEvents() async {
        let api = FakeAPI()
        api.set {
            $0.pixies = [Island.pixie("p1", name: "Brook")]
            $0.details["hs-r1"] = Fixture.session("hs-r1")
            $0.habits = [
                "p1": [
                    PixieHabitsTests.habit(
                        lastRun: PixieHabitsTests.runJSON(
                            outcome: "running", started: #""2026-10-14T09:00:00Z""#,
                            ended: "null"))
                ]
            ]
        }
        let clock = Clock()
        clock.now = Fixture.date("2026-10-14T09:01:00Z")
        let model = model(api, prefs: MemoryStore(), clock: clock)
        // Installed before the run.
        let installed = model.island.installedAt
        #expect(installed == clock.now)
        clock.now = Fixture.date("2026-10-14T09:05:00Z")
        await model.live.refresh()
        #expect(model.island.state().left.map(\.id) == ["habit:hs-r1"])

        model.live.route(
            Fixture.event(
                EventType.habitRunUpdated,
                #"{"run": \#(PixieHabitsTests.runJSON(outcome: "reported", ended: #""2026-10-14T09:04:00Z""#))}"#,
                session: nil))
        #expect(model.island.state().left.isEmpty)
        #expect(model.island.state().right.map(\.id) == ["habit:hs-r1"])
    }

    /// A chat with a working pixie has its agents read once per connect, for the rows.
    @Test func workingChatsHaveTheirAgentsReadOnce() async {
        let api = FakeAPI()
        setUp(api)
        api.set { $0.approvals = [] }
        let model = model(api, prefs: MemoryStore(), clock: Clock())
        await model.live.refresh()
        await model.island.loadActivity(model.island.state())
        #expect(api.calls.filter { $0 == "session s1" }.count == 1)
        await model.live.refresh()
        #expect(api.calls.filter { $0 == "session s1" }.count == 2)
    }
}
