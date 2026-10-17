import Foundation
import Testing

@testable import NestKit

/// Pixies in these teams, by id, in this order; slugs are the ids.
private func pixies(_ rows: (id: String, team: String?)...) -> [Pixie] {
    rows.enumerated().map { index, row in
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie.id = row.id
        pixie.slug = row.id
        pixie.name = row.id.capitalized
        pixie.position = index
        pixie.teamID = row.team
        return pixie
    }
}

private func team(_ id: String, _ position: Int, leader: String?, handle: String? = nil)
    -> PixieTeam
{
    var team = Fixture.decode(PixieTeam.self, "pixie_team")
    team.id = id
    team.name = id.uppercased()
    team.handle = handle ?? id
    team.position = position
    team.leaderID = leader
    return team
}

@Suite struct PixieTeamModelTests {
    @Test func aTeamAndAPixiesTeamDecode() throws {
        let team = Fixture.decode(PixieTeam.self, "pixie_team")
        #expect(team.id == "t1")
        #expect(team.name == "QA")
        #expect(team.handle == "qa")
        #expect(team.leaderID == "p1")
        #expect(team.position == 0)
        #expect(Fixture.decode(Pixie.self, "pixie").teamID == nil)
        // An older daemon's pixie, without the field, has no team.
        let older = Fixture.text("pixie").replacingOccurrences(of: #""team_id": null,"#, with: "")
        #expect(Fixture.decode(Pixie.self, json: older).teamID == nil)
        let member = Fixture.text("pixie").replacingOccurrences(
            of: #""team_id": null"#, with: #""team_id": "t1""#)
        #expect(Fixture.decode(Pixie.self, json: member).teamID == "t1")
    }

    @Test func joiningOrLeavingATeamShowsAtOnce() {
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie = pixie.applying(UpdatePixieRequest(teamID: "t1"))
        #expect(pixie.teamID == "t1")
        #expect(pixie.applying(UpdatePixieRequest(name: "X")).teamID == "t1")
        #expect(pixie.applying(UpdatePixieRequest(leavesTeam: true)).teamID == nil)
        // A team named as well wins.
        #expect(pixie.applying(UpdatePixieRequest(teamID: "t2", leavesTeam: true)).teamID == "t2")
    }

    @Test func teamEventsDecode() {
        let updated = Fixture.event(
            EventType.pixieTeamUpdated, #"{"team": \#(Fixture.text("pixie_team"))}"#)
        #expect(updated.body == .pixieTeamUpdated(Fixture.decode(PixieTeam.self, "pixie_team")))
        let deleted = Fixture.event(EventType.pixieTeamDeleted, #"{"id": "t1"}"#)
        #expect(deleted.body == .pixieTeamDeleted("t1"))
        #expect(Fixture.event(EventType.pixieTeamDeleted, #"{"team_id": "t1"}"#).body == .other)
    }

    @Test func confirmationsNameWhatGoes() {
        #expect(
            PixieConfirm.deletePixie("Reviewer").text
                == "Delete Reviewer? Its chat, soul and memory go too. This can't be undone.")
        #expect(PixieConfirm.deletePixie("Reviewer").title == "Delete Reviewer?")
        #expect(PixieConfirm.deleteTeam("QA").text == "Delete QA? Its pixies stay, without a team.")
        #expect(PixieConfirm.deleteTeam("QA").message == "Its pixies stay, without a team.")
    }
}

@MainActor @Suite struct PixieTeamsStoreTests {
    @Test func loadsTeamsInOrderAndAppliesTheirEvents() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixies = pixies(("a", "t2"), ("b", nil))
            $0.teams = [team("t2", 1, leader: "a"), team("t1", 0, leader: nil)]
        }
        let store = PixiesStore(api: api)
        try await store.load()
        #expect(store.teams.map(\.id) == ["t1", "t2"])

        var renamed = team("t1", 0, leader: nil)
        renamed.name = "Quality"
        renamed.updatedAt = Date(timeIntervalSince1970: 2_000_000_000)
        store.apply(
            Fixture.event(EventType.pixieTeamUpdated, #"{"team": \#(Fixture.json(renamed))}"#))
        #expect(store.team("t1")?.name == "Quality")
        // An older copy is ignored; a new team is added in its place.
        var older = renamed
        older.name = "Old"
        older.updatedAt = Date(timeIntervalSince1970: 0)
        store.apply(
            Fixture.event(EventType.pixieTeamUpdated, #"{"team": \#(Fixture.json(older))}"#))
        #expect(store.team("t1")?.name == "Quality")
        store.apply(
            Fixture.event(
                EventType.pixieTeamUpdated,
                #"{"team": \#(Fixture.json(team("t0", 2, leader: nil)))}"#
            ))
        #expect(store.teams.map(\.id) == ["t1", "t2", "t0"])

        // A team deleted elsewhere: its pixies show without a team at once.
        store.apply(Fixture.event(EventType.pixieTeamDeleted, #"{"id": "t2"}"#))
        #expect(store.teams.map(\.id) == ["t1", "t0"])
        #expect(store.pixies.map(\.teamID) == [nil, nil])
        #expect(store.team("t2") == nil)
    }

    @Test func createsRenamesAndDeletesTeams() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixies = pixies(("a", "t1"), ("b", "t1"))
            $0.teams = [team("t1", 0, leader: "a")]
        }
        let store = PixiesStore(api: api)
        try await store.load()

        let created = try await store.createTeam(name: "Docs")
        #expect(created.position == 1)
        #expect(store.teams.map(\.name) == ["T1", "Docs"])

        try await store.updateTeam("t1", UpdatePixieTeamRequest(leaderID: "b"))
        #expect(store.team("t1")?.leaderID == "b")
        // The leader must be a member: the daemon refuses, and nothing changes.
        await #expect(throws: APIError.self) {
            try await store.updateTeam("t1", UpdatePixieTeamRequest(leaderID: "zz"))
        }
        #expect(store.team("t1")?.leaderID == "b")

        try await store.deleteTeam("t1")
        #expect(store.teams.map(\.name) == ["Docs"])
        #expect(store.pixies.allSatisfy { $0.teamID == nil })
        #expect(
            api.calls.filter { $0.contains("Team") } == [
                "pixieTeams", "createPixieTeam Docs", "updatePixieTeam t1", "updatePixieTeam t1",
                "deletePixieTeam t1",
            ])
    }

    @Test func aPixieJoinsAndLeavesATeam() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixies = pixies(("a", nil), ("b", "t1"))
            $0.teams = [team("t1", 0, leader: "b")]
        }
        let store = PixiesStore(api: api)
        try await store.load()

        try await store.setTeam("a", to: "t1")
        #expect(store.pixies[0].teamID == "t1")
        try await store.setTeam("b", to: nil)
        #expect(store.pixies[1].teamID == nil)
        #expect(
            api.calls.filter { $0.hasPrefix("updatePixie ") } == ["updatePixie a", "updatePixie b"])
    }

    /// A pixie dropped on one in another section joins that section's team, then takes
    /// its place; within a section it only moves.
    @Test func aPixieDroppedOnAnotherJoinsItsTeam() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixies = pixies(("a", nil), ("b", "t1"), ("c", "t1"))
            $0.teams = [team("t1", 0, leader: "b")]
        }
        let store = PixiesStore(api: api)
        try await store.load()

        try await store.place("a", onto: "c")
        #expect(store.pixies.map(\.id) == ["b", "c", "a"])
        #expect(store.pixies.first { $0.id == "a" }?.teamID == "t1")
        try await store.place("a", onto: "b")
        #expect(store.pixies.map(\.id) == ["a", "b", "c"])
        #expect(api.calls.count { $0.hasPrefix("updatePixie ") } == 1)
        // Unknown pixies: nothing.
        try await store.place("x", onto: "a")
        try await store.place("a", onto: "x")
        #expect(api.calls.count { $0.hasPrefix("reorder") } == 2)
    }

    /// The copy shows right under the original at once; the pixies after it move down.
    @Test func duplicatesAPixieUnderTheOriginal() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = pixies(("a", "t1"), ("b", nil)) }
        let store = PixiesStore(api: api)
        try await store.load()

        let copy = try await store.duplicate("a")
        #expect(copy.name == "A 2")
        #expect(store.pixies.map(\.id) == ["a", copy.id, "b"])
        #expect(store.pixies.map(\.position) == [0, 1, 2])
        #expect(store.pixies[1].teamID == "t1")
    }

    @Test func soulLinesLoadOncePerPixie() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixies = pixies(("a", nil), ("b", nil))
            $0.pixieFiles["soul"] = PixieFile(text: "\n  # Reviewer  \nMore", hash: "h")
        }
        let store = PixiesStore(api: api)
        try await store.load()

        await store.loadSoulLines(["a"])
        await store.loadSoulLines(["a", "b"])
        #expect(store.soulLines == ["a": "# Reviewer", "b": "# Reviewer"])
        #expect(
            api.calls.filter { $0.hasPrefix("pixieFile") } == [
                "pixieFile a soul", "pixieFile b soul",
            ])

        // Saving the soul here shows its new first line.
        _ = try await store.save("a", name: "soul", text: "Tests first.", hash: "h")
        #expect(store.soulLines["a"] == "Tests first.")
        _ = try await store.save("a", name: "memory", text: "x", hash: "h")
        #expect(store.soulLines["a"] == "Tests first.")

        // A failed read is asked for again next time.
        let other = FakeAPI()
        other.fail("pixieFile")
        let failing = PixiesStore(api: other)
        await failing.loadSoulLines(["a"])
        #expect(failing.soulLines.isEmpty)
        await failing.loadSoulLines(["a"])
        #expect(other.calls.count { $0.hasPrefix("pixieFile") } == 2)
    }

    @Test func foldedTeamsAreRemembered() {
        let defaults = MemoryStore()
        let app = AppStore(api: FakeAPI(), store: defaults)
        #expect(app.foldedTeams.isEmpty)
        app.toggleTeamFold("t1")
        app.toggleTeamFold("t2")
        #expect(app.foldedTeams == ["t1", "t2"])
        app.toggleTeamFold("t1")
        #expect(app.foldedTeams == ["t2"])
        #expect(AppStore(api: FakeAPI(), store: defaults).foldedTeams == ["t2"])
        app.toggleTeamFold("t2")
        #expect(defaults.string(forKey: "pixies.foldedTeams") == nil)
    }
}

@Suite struct PixieListLayoutTests {
    @Test func teamsComeFirstWithTheirMembersThenPixiesWithoutATeam() {
        let list = pixies(("a", nil), ("b", "t2"), ("c", "t1"), ("d", "t2"), ("e", "gone"))
        let teams = [
            team("t2", 1, leader: "d"), team("t1", 0, leader: "c"), team("t3", 2, leader: nil),
        ]
        let sections = PixieListLayout.sections(list, teams: teams)
        #expect(sections.teams.map(\.team.id) == ["t1", "t2", "t3"])
        #expect(sections.teams.map { $0.members.map(\.id) } == [["c"], ["b", "d"], []])
        // A pixie whose team is not known yet shows without one.
        #expect(sections.loose.map(\.id) == ["a", "e"])
        #expect(sections.teams[1].id == "t2")
        #expect(sections.teams[1].isLeader(list[3]))
        #expect(!sections.teams[1].isLeader(list[1]))

        // Move Up and Move Down stay within the pixie's section.
        #expect(sections.neighbors(of: "d") == ["b", "d"])
        #expect(sections.neighbors(of: "e") == ["a", "e"])
        #expect(sections.neighbors(of: "zz") == [])
    }
}

@Suite struct PixieMentionTests {
    /// Every pixie may work in every project (B85), unless hidden or without project files.
    @Test func aPixieIsCallableUnlessHiddenOrWithoutProjectFiles() {
        var pixie = Fixture.decode(Pixie.self, "pixie")
        #expect(pixie.isCallable)
        pixie.projectAccess = .read
        #expect(pixie.isCallable)
        pixie.projectAccess = .noAccess
        #expect(!pixie.isCallable)
        pixie.projectAccess = .edit
        pixie.hidden = true
        #expect(!pixie.isCallable)
    }

    /// Add in Skills (B85): the skills a pixie may use, from `GET /api/pixies/skills`, not
    /// chosen yet; standalone ones first, then one group per plugin, each by name.
    @Test func skillsToAddAreGroupedByPlugin() {
        let choices = [
            PixieSkillChoice(
                name: "code-review:review", description: "Reviews", plugin: "code-review"),
            PixieSkillChoice(name: "notes", description: nil, plugin: nil),
            PixieSkillChoice(name: "pdf:fill", description: nil, plugin: "pdf"),
            PixieSkillChoice(name: "code-review:diff", description: nil, plugin: "code-review"),
            PixieSkillChoice(name: "release-notes", description: nil, plugin: nil),
        ]
        let menu = PixieSkillMenu(choices: choices, chosen: ["notes", "pdf:fill"])
        #expect(menu.standalone.map(\.name) == ["release-notes"])
        #expect(menu.groups.map(\.plugin) == ["code-review"])
        #expect(menu.groups[0].skills.map(\.name) == ["code-review:diff", "code-review:review"])
        #expect(menu.groups[0].id == "code-review")
        #expect(menu.groups[0].skills.map(\.shortName) == ["diff", "review"])
        #expect(menu.standalone[0].shortName == "release-notes")
        #expect(menu.groups[0].skills[1].id == "code-review:review")
        #expect(!menu.isEmpty)
        #expect(menu.emptyText == nil)
        // Groups go by plugin name, standalone ones by name.
        let all = PixieSkillMenu(choices: choices, chosen: [])
        #expect(all.groups.map(\.plugin) == ["code-review", "pdf"])
        #expect(all.standalone.map(\.name) == ["notes", "release-notes"])
        let done = PixieSkillMenu(choices: choices, chosen: choices.map(\.name))
        #expect(done.isEmpty)
        #expect(done.emptyText == "Every installed skill is added")
        #expect(PixieSkillMenu(choices: [], chosen: []).emptyText == "No skills installed")
        #expect(
            Fixture.decode(
                [PixieSkillChoice].self,
                json: #"[{"name": "pdf:fill", "description": null, "plugin": "pdf"}]"#)
                == [PixieSkillChoice(name: "pdf:fill", description: nil, plugin: "pdf")])
    }

    @MainActor @Test func theStoreReadsTheSkillsAPixieMayUse() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixieSkills = [PixieSkillChoice(name: "notes", description: nil, plugin: nil)]
        }
        let store = PixiesStore(api: api)
        #expect(store.skillChoices == nil)
        try await store.loadSkillChoices()
        #expect(store.skillChoices?.map(\.name) == ["notes"])
        #expect(api.calls == ["pixieSkills"])
    }

    @Test func availableTeamsComeBeforePixies() {
        var list = pixies(
            ("a", "t1"), ("b", "t1"), ("c", nil), ("d", "t2"), ("e", "t3"), ("f", "t1"),
            ("g", "t3"))
        list[1].hidden = true
        list[4].projectAccess = .noAccess
        let teams = [
            team("t1", 0, leader: "a", handle: "qa"),
            // Its leader may not work here: left out, so its members are called alone.
            team("t3", 1, leader: "e"),
            team("t2", 2, leader: "d"),
            // No members: left out.
            team("t4", 3, leader: nil),
            // A leader that is not a member (a stale event): left out.
            team("t5", 4, leader: "c"),
        ]
        let mentions = PixieMentions.available(
            pixies: list, teams: teams, souls: ["c": "Reviews."])
        // A member of an offered team is called only through its team (B46).
        #expect(mentions.map(\.token) == ["qa", "t2", "c", "g"])
        guard case .team(let qa, let members) = mentions[0] else {
            Issue.record("not a team")
            return
        }
        #expect(qa.id == "t1")
        // Only the members available here.
        #expect(members.map(\.id) == ["a", "f"])
        #expect(mentions[2] == .pixie(list[2], soul: "Reviews."))
        #expect(mentions[3] == .pixie(list[6], soul: nil))
        #expect(mentions.map(\.id) == ["team:t1", "team:t2", "pixie:c", "pixie:g"])
        #expect(mentions.map(\.name) == ["T1", "T2", "C", "G"])
    }

    @Test func typingFiltersByHandleOrName() {
        var list = pixies(("rev", nil), ("tester", "t1"))
        list[0].name = "Reviewer"
        let mentions = PixieMentions.available(
            pixies: list, teams: [team("t1", 0, leader: "tester", handle: "qa")], souls: [:])
        #expect(PixieMentions.matching(mentions, query: "").count == 2)
        #expect(PixieMentions.matching(mentions, query: "RE").map(\.token) == ["rev"])
        #expect(PixieMentions.matching(mentions, query: "q").map(\.token) == ["qa"])
        // A team's member is not offered on its own (B46).
        #expect(PixieMentions.matching(mentions, query: "tes").isEmpty)
        #expect(PixieMentions.matching(mentions, query: "T1").map(\.token) == ["qa"])
        #expect(PixieMentions.matching(mentions, query: "zz").isEmpty)
    }

    @Test func aSoulsFirstLineIsItsFirstTextLine() {
        #expect(PixieSoul.firstLine("\n\n  I review code.  \nMore") == "I review code.")
        #expect(PixieSoul.firstLine(" \n ") == nil)
        #expect(PixieSoul.firstLine("") == nil)
    }
}

@MainActor @Suite struct MentionCompletionTests {
    let reviewer: Pixie = {
        var pixie = Fixture.decode(Pixie.self, "pixie")
        pixie.id = "p1"
        pixie.slug = "reviewer"
        pixie.name = "Reviewer"
        return pixie
    }()

    @Test func pixiesComeFirstThenFiles() {
        let mentions: [PixieMention] = [
            .team(team("t1", 0, leader: "p1", handle: "qa"), members: [reviewer]),
            .pixie(reviewer, soul: "I review."),
        ]
        let text = "ask @ now"
        let trigger = CompletionTrigger.at(text, caret: 5)!
        let list = CompletionList.mentions(
            mentions, files: ["src/app.ts"], for: trigger, in: text)
        #expect(list.items.map(\.label) == ["T1", "Reviewer", "src/app.ts"])
        #expect(list.items.map(\.id) == ["team:t1", "pixie:p1", "src/app.ts"])
        #expect(list.items[0].text == "ask @qa now")
        #expect(list.items[0].caret == 8)
        #expect(list.items[0].hint == "@qa")
        #expect(list.items[1].text == "ask @reviewer now")
        #expect(list.items[1].detail == "I review.")
        #expect(list.items[2].mention == nil)
        #expect(list.items[0].mention == mentions[0])
        #expect(
            list.sections.map { section in section.title } == ["Pixies", "Files"])
        #expect(list.sections.map { $0.rows.map(\.index) } == [[0, 1], [2]])
        #expect(list.sections.map(\.id) == ["Pixies", "Files"])
        #expect(list.title == "Files")

        let onlyFiles = CompletionList.mentions([], files: ["a"], for: trigger, in: text)
        #expect(onlyFiles.sections.map(\.title) == ["Files"])
        let onlyPixies = CompletionList.mentions(mentions, files: [], for: trigger, in: text)
        #expect(onlyPixies.sections.map(\.title) == ["Pixies"])
        // Commands have one section of their own.
        let commands = CompletionList.commands(
            [], for: CompletionTrigger.at("/", caret: 1)!, in: "/")
        #expect(commands.sections.isEmpty)
    }

    @Test func theStoreOffersPixiesWhereGiven() async {
        let api = FakeAPI()
        api.set { $0.files["re"] = ["src/review.ts"] }
        let store = CompletionStore(api: api)
        await store.searchFiles(session: "s1", query: "re")
        let mentions: [PixieMention] = [.pixie(reviewer, soul: nil)]

        let list = store.suggestions(
            text: "@re", caret: 3, session: "s1", repo: "cv-page", mentions: mentions)
        #expect(list?.items.map(\.label) == ["Reviewer", "src/review.ts"])
        // Typing filters the pixies too.
        let none = store.suggestions(
            text: "@zz", caret: 3, session: "s1", repo: "cv-page", mentions: mentions)
        #expect(none?.items.map(\.label) == ["src/review.ts"])
        // A new chat has no files yet, but pixies.
        let draft = store.suggestions(
            text: "@", caret: 1, session: nil, repo: "cv-page", mentions: mentions)
        #expect(draft?.items.map(\.label) == ["Reviewer"])
        // Not offered (a pixie chat, a Claude Code chat): files only, as before.
        let plain = store.suggestions(text: "@re", caret: 3, session: "s1", repo: "cv-page")
        #expect(plain?.items.map(\.label) == ["src/review.ts"])
        #expect(store.suggestions(text: "@", caret: 1, session: nil, repo: "cv-page") == nil)
    }
}

@Suite struct MentionHighlightTests {
    func highlights(_ text: String) -> [String] {
        var list = pixies(("reviewer", "t1"), ("qa-bot", nil))
        list[0].color = "#8B7CF6"
        list[1].color = "#E5484D"
        let teams = [
            team("t1", 0, leader: "reviewer", handle: "qa"),
            team("t2", 1, leader: nil, handle: "docs"),
            team("t3", 2, leader: "gone", handle: "ops"),
        ]
        let found = MentionHighlights.find(in: text, pixies: list, teams: teams)
        return found.map { highlight in
            "\((text as NSString).substring(with: highlight.range)) \(highlight.color)"
        }
    }

    @Test func pixieAndTeamMentionsTakeTheirColour() {
        #expect(
            highlights("@reviewer look, then ask @qa (and @qa-bot).")
                == ["@reviewer #8B7CF6", "@qa #8B7CF6", "@qa-bot #E5484D"])
        // After a line break or a tab too.
        #expect(highlights("hi\n@reviewer\t@qa") == ["@reviewer #8B7CF6", "@qa #8B7CF6"])
        // Offsets count UTF-16 units, as the text view does.
        #expect(highlights("👋 @qa") == ["@qa #8B7CF6"])
    }

    @Test func onlyWholeKnownTokensCount() {
        // Inside a word, an email, longer names, unknown names, other case.
        #expect(highlights("me@reviewer.com").isEmpty)
        #expect(highlights("@reviewers @qa_x @qa-x @nobody @Reviewer").isEmpty)
        #expect(highlights("@ alone @").isEmpty)
        // A team without a leader, or whose leader is gone, stays plain.
        #expect(highlights("@docs @ops").isEmpty)
        #expect(highlights("").isEmpty)
    }
}

@Suite struct TeamLeaderColorTests {
    @Test func aTeamTakesItsLeadersCurrentColour() {
        var list = pixies(("reviewer", "t1"), ("qa-bot", "t1"))
        list[0].color = "#8B7CF6"
        list[1].color = "#E5484D"
        var qa = team("t1", 0, leader: "reviewer")
        #expect(qa.leaderColor(among: list) == "#8B7CF6")
        // A new leader, or the leader's new colour, shows at once.
        qa.leaderID = "qa-bot"
        #expect(qa.leaderColor(among: list) == "#E5484D")
        list[1].color = "#30A46C"
        #expect(qa.leaderColor(among: list) == "#30A46C")
    }

    @Test func noLeaderOrAnUnknownOneHasNoColour() {
        let list = pixies(("reviewer", "t1"))
        #expect(team("t1", 0, leader: nil).leaderColor(among: list) == nil)
        #expect(team("t1", 0, leader: "gone").leaderColor(among: list) == nil)
        #expect(team("t1", 0, leader: "reviewer").leaderColor(among: []) == nil)
    }
}

@MainActor @Suite struct PixieJumpTests {
    /// A pixie call's name opens the pixie's pane as a list click does, focused, even when
    /// the Pixies workspace has not been measured yet; opening it again only focuses it.
    @Test func aJumpOpensAndFocusesThePane() {
        let store = MemoryStore()
        let app = AppStore(api: FakeAPI(), store: store)
        app.openPixie("reviewer", in: .zero)
        #expect(app.pixieState.layout.leaves == ["reviewer"])
        #expect(app.pixieState.layout.focused == "reviewer")
        // Unmeasured: the next one is placed as in a restored window, side by side.
        app.openPixie("watcher", in: CGSize(width: 0, height: 700))
        #expect(app.pixieState.layout.leaves == ["reviewer", "watcher"])
        app.openPixie("reviewer", in: CGSize(width: 900, height: 0))
        #expect(app.pixieState.layout.leaves == ["reviewer", "watcher"])
        #expect(app.pixieState.layout.focused == "reviewer")
        #expect(store.string(forKey: "pixies.panes") == "reviewer\nwatcher")
        // A measured workspace is used as it is: too narrow for two side by side.
        let narrow = AppStore(api: FakeAPI(), store: MemoryStore())
        narrow.openPixie("a", in: CGSize(width: 500, height: 700))
        narrow.openPixie("b", in: CGSize(width: 500, height: 700))
        let frames = narrow.pixieState.layout.paneFrames(in: CGSize(width: 500, height: 700))
        #expect(frames.map(\.frame.minX) == [0, 0])
        #expect(narrow.pixieState.layout.leaves == ["a", "b"])
    }
}

@Suite struct PixiePromptTests {
    let teams = [team("t1", 0, leader: nil, handle: "qa")]

    /// Rename and Change handle start from the team's current name or handle (shown
    /// selected); New team starts empty.
    @Test func typedPromptsStartFromWhatIsThere() {
        #expect(PixiePrompt.renameTeam("t1").startText(teams: teams) == "T1")
        #expect(PixiePrompt.teamHandle("t1").startText(teams: teams) == "qa")
        #expect(PixiePrompt.newTeam.startText(teams: teams) == "")
        #expect(PixiePrompt.renameTeam("gone").startText(teams: teams) == "")
        #expect(PixiePrompt.teamHandle("gone").startText(teams: teams) == "")
        #expect(PixiePrompt.deleteTeam("t1").startText(teams: teams) == "")
    }

    @Test func eachPromptSaysWhatItAsks() {
        let typed: [PixiePrompt] = [.newTeam, .renameTeam("t1"), .teamHandle("t1")]
        #expect(typed.map(\.isTyped) == [true, true, true])
        #expect(typed.map(\.title) == ["New team", "Rename team", "Change handle"])
        #expect(typed.map(\.field) == ["Name", "Name", "Handle"])
        #expect(typed.map(\.action) == ["Create", "Rename", "Save"])
        #expect(typed.map { $0.note != nil } == [false, false, true])
        let confirmed: [PixiePrompt] = [.deletePixie("p1"), .deleteTeam("t1")]
        #expect(confirmed.map(\.isTyped) == [false, false])
        #expect(confirmed.map(\.action) == ["Delete", "Delete"])
        #expect(confirmed.map(\.title) == ["Delete pixie", "Delete team"])
    }
}

@Suite struct TeamCallTests {
    /// QA's leader is Bugs; Solo has no team; Docs has no leader and Gone's leader is not
    /// known.
    let known: [Pixie] = {
        var list = pixies(
            ("stylist", "qa"), ("bugs", "qa"), ("solo", nil), ("scout", "qa"), ("idle", "docs"))
        list[1].color = "#E5484D"
        return list
    }()
    let teams = [
        team("qa", 0, leader: "bugs"), team("docs", 1, leader: nil),
        team("gone", 2, leader: "nobody"),
    ]

    private func teamCall(_ slug: String, pixieChat: Bool = false) -> TeamCall? {
        PixieCalls.team(of: slug, pixies: known, teams: teams, pixieChat: pixieChat)
    }

    /// In a project chat the main agent calls only a team's leader, so a leader's call is
    /// its team's, drawn in the leader's colour with the leader first (B70).
    @Test func aProjectChatsCallOfALeaderIsItsTeamsCall() throws {
        let call = try #require(teamCall("bugs"))
        #expect(call.team.id == "qa")
        #expect(call.color == "#E5484D")
        #expect(call.members.map(\.id) == ["bugs", "stylist", "scout"])
    }

    @Test func otherCallsStayPixieCalls() {
        // A member who does not lead, a pixie with no team, an unknown slug.
        #expect(teamCall("stylist") == nil)
        #expect(teamCall("solo") == nil)
        #expect(teamCall("nobody") == nil)
        // A member of a team with no leader.
        #expect(teamCall("idle") == nil)
        // In a pixie's own chat its calls are its own.
        #expect(teamCall("bugs", pixieChat: true) == nil)
    }

    @Test func whileItRunsTheLabelSaysTheTeamIsWorking() throws {
        let call = try #require(teamCall("bugs"))
        #expect(call.label(running: true) == "QA working")
        #expect(call.label(running: false) == "QA")
    }

    @Test func itsMarkIsTheTeamsGridHoppingWhileItRuns() throws {
        let call = try #require(teamCall("bugs"))
        let working = call.icon(working: true)
        #expect(working.map(\.pixie.id) == ["bugs", "stylist", "scout", "bugs"])
        #expect(working.map(\.working) == [true, true, true, true])
        #expect(working.map(\.phaseKey) == ["bugs#0", "stylist#1", "scout#2", "bugs#3"])
        #expect(call.icon(working: false).map(\.working) == [false, false, false, false])
    }

    /// A click opens the team's work in this chat, as the chat tree's team row does: with
    /// the members of the chat's entry for the team, else the team's current members.
    @Test func aClickOpensTheTeamsWork() throws {
        let call = try #require(teamCall("bugs"))
        #expect(
            call.work(session: "c1", group: [])
                == .team(session: "c1", teamID: "qa", members: ["bugs", "stylist", "scout"]))
        let entry: ChatPixieEntry = try NestJSON.decoder.decode(
            ChatPixieEntry.self,
            from: Data(
                """
                {"kind": "team", "pixie_id": null, "team_id": "qa", "state": "done",
                 "calls": [], "members": [
                   {"pixie_id": "bugs", "leader": true, "state": "done"},
                   {"pixie_id": "stylist", "leader": false, "state": null}
                 ]}
                """.utf8))
        let other: ChatPixieEntry = try NestJSON.decoder.decode(
            ChatPixieEntry.self,
            from: Data(
                """
                {"kind": "pixie", "pixie_id": "solo", "team_id": null, "state": "done",
                 "calls": [], "members": []}
                """.utf8))
        #expect(
            call.work(session: "c1", group: [other, entry])
                == .team(session: "c1", teamID: "qa", members: ["bugs", "stylist"]))
    }
}
