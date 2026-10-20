import Foundation
import Testing

@testable import NestKit

@MainActor @Suite struct PixiesStoreTests {
    @Test func loadsSortsAndAppliesEvents() async throws {
        let api = FakeAPI()
        let first = try Fixture.decode(Pixie.self, "pixie")
        var second = first
        second.id = "p2"
        second.position = 1
        second.hidden = true
        api.set { $0.pixies = [second, first] }
        let store = PixiesStore(api: api)

        try await store.load()
        #expect(store.pixies.map(\.id) == ["p1", "p2"])
        #expect(store.visible.map(\.id) == ["p1"])

        store.apply(
            Fixture.event(
                EventType.pixieUpdated,
                ##"{"pixie": {"id": "p1", "slug": "tester", "name": "QA", "mascot": "sprig", "##
                    + ##""color": "#8B7CF6", "model": null, "effort": null, "##
                    + ##""permission_mode": "default", "autonomy": "observe", "project_access": "edit", "##
                    + ##""skills": [], "can_call": [], "hidden": false, "##
                    + ##""position": 0, "chat_session_id": null, "max_running": 2, "max_per_day": 5, "unread_action_reports": 0, "##
                    + ##""created_at": "2026-10-13T09:00:00Z", "updated_at": "2026-10-13T09:00:00Z"}}"##
            ))
        // An older copy, such as an event that arrives after a later answer, is ignored.
        var older = store.pixies[0]
        older.name = "Old"
        older.updatedAt = Date(timeIntervalSince1970: 0)
        store.apply(Fixture.event(EventType.pixieUpdated, #"{"pixie": \#(Fixture.json(older))}"#))
        #expect(store.pixies[0].name == "QA")
        store.apply(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p2"}"#))
        #expect(store.pixies.map(\.name) == ["QA"])
        store.apply(Fixture.event(EventType.sessionCreated, #"{"session": null}"#))
        #expect(store.pixies.count == 1)
    }

    @Test func sendsAndSaves() async throws {
        let api = FakeAPI()
        let store = PixiesStore(api: api)

        let sent = try await store.send("p1", text: "hi")
        #expect(sent.session.pixieID == "p1")
        #expect(sent.queuedMessage == nil)
        _ = try await store.save("p1", name: "soul", text: "x", hash: "h")
        #expect(api.calls == ["sendToPixie p1", "savePixieFile p1 soul"])
    }

    /// A message sent while the pixie's chat works comes back queued, as in a normal chat.
    @Test func aSendWhileTheChatWorksIsQueued() async throws {
        let api = FakeAPI()
        api.set { $0.queueSends = true }
        let store = PixiesStore(api: api)

        let sent = try await store.send("p1", text: "later")
        #expect(sent.queuedMessage?.text == "later")
    }

    static func pixies(_ ids: String...) -> [Pixie] {
        ids.enumerated().map { index, id in
            var pixie = Fixture.decode(Pixie.self, "pixie")
            pixie.id = id
            pixie.slug = id
            pixie.position = index
            return pixie
        }
    }

    /// A pixie dropped on another takes its place: below it when dragged down, above it
    /// when dragged up. The list moves at once and the daemon gets every pixie in order.
    @Test func movesAPixieOntoAnother() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a", "b", "c") }
        let store = PixiesStore(api: api)
        try await store.load()

        try await store.move("a", onto: "c")
        #expect(store.pixies.map(\.id) == ["b", "c", "a"])
        #expect(store.pixies.map(\.position) == [0, 1, 2])
        try await store.move("a", onto: "b")
        #expect(store.pixies.map(\.id) == ["a", "b", "c"])
        #expect(
            api.calls.filter { $0.hasPrefix("reorder") } == [
                "reorderPixies b,c,a", "reorderPixies a,b,c",
            ])

        // Onto itself or an unknown pixie: nothing to send.
        try await store.move("a", onto: "a")
        try await store.move("x", onto: "a")
        try await store.move("a", onto: "x")
        #expect(api.calls.count { $0.hasPrefix("reorder") } == 2)
    }

    @Test func movesAPixieUpAndDownTheListed() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a", "b", "c") }
        let store = PixiesStore(api: api)
        try await store.load()

        try await store.move("b", by: -1, among: ["a", "b", "c"])
        #expect(store.pixies.map(\.id) == ["b", "a", "c"])
        try await store.move("b", by: 1, among: ["b", "c"])
        #expect(store.pixies.map(\.id) == ["a", "c", "b"])
        // Past either end: nothing.
        try await store.move("b", by: 1, among: ["a", "c", "b"])
        try await store.move("a", by: -1, among: ["a", "c", "b"])
        try await store.move("x", by: 1, among: ["a", "c", "b"])
        #expect(store.pixies.map(\.id) == ["a", "c", "b"])
        #expect(api.calls.count { $0.hasPrefix("reorder") } == 2)
    }

    @Test func aRefusedOrderIsRolledBack() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a", "b") }
        api.fail("reorderPixies", with: APIError.invalidInput("the order must name every pixie"))
        let store = PixiesStore(api: api)
        try await store.load()

        await #expect(throws: APIError.invalidInput("the order must name every pixie")) {
            try await store.move("a", onto: "b")
        }
        #expect(store.pixies.map(\.id) == ["a", "b"])
        #expect(store.pixies.map(\.position) == [0, 1])
    }

    /// The new order shows while the daemon saves it.
    @Test func theNewOrderShowsAtOnce() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a", "b") }
        let store = PixiesStore(api: api)
        try await store.load()
        let gate = AsyncStream.makeStream(of: Void.self)
        api.set { $0.gates["reorderPixies"] = gate.stream }

        let moving = Task { try await store.move("b", onto: "a") }
        try await waitFor { store.pixies.map(\.id) == ["b", "a"] }
        #expect(!api.calls.contains("reorderPixies b,a"))
        gate.continuation.finish()
        try await moving.value
        #expect(store.pixies.map(\.id) == ["b", "a"])
    }

    /// Two quick drags: the first is refused after the second was saved. The list shows
    /// what the daemon holds, the second drag's order, not the one before the first.
    @Test func aRefusedMoveUnderANewerOneShowsTheDaemonsOrder() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a", "b", "c") }
        let store = PixiesStore(api: api)
        try await store.load()
        let gate = AsyncStream.makeStream(of: Void.self)
        api.set {
            $0.gates["reorderPixies"] = gate.stream
            $0.failNext["reorderPixies"] = APIError.invalidInput("the order changed")
        }

        let first = Task { try await store.move("a", onto: "c") }
        try await waitFor { store.pixies.map(\.id) == ["b", "c", "a"] }
        let second = Task { try await store.move("b", onto: "a") }
        try await waitFor { store.pixies.map(\.id) == ["c", "a", "b"] }
        gate.continuation.finish()
        await #expect(throws: APIError.invalidInput("the order changed")) {
            try await first.value
        }
        try await second.value

        // In turn: the second waited for the first.
        #expect(
            api.calls.filter { $0.hasPrefix("reorder") } == [
                "reorderPixies b,c,a", "reorderPixies c,a,b",
            ])
        #expect(api.state.withLock { $0.pixies.map(\.id) } == ["c", "a", "b"])
        #expect(store.pixies.map(\.id) == ["c", "a", "b"])
        #expect(store.pixies.map(\.position) == [0, 1, 2])
    }

    /// A pixie created while a drag saves keeps its place at the end of a rolled-back list.
    @Test func aRolledBackOrderKeepsPixiesAddedMeanwhile() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a", "b") }
        api.fail("reorderPixies", with: APIError.invalidInput("the order changed"))
        let store = PixiesStore(api: api)
        try await store.load()
        let gate = AsyncStream.makeStream(of: Void.self)
        api.set { $0.gates["reorderPixies"] = gate.stream }

        let moving = Task { try await store.move("b", onto: "a") }
        try await waitFor { store.pixies.map(\.id) == ["b", "a"] }
        _ = try await store.create(CreatePixieRequest(name: "C"))
        gate.continuation.finish()
        await #expect(throws: APIError.invalidInput("the order changed")) {
            try await moving.value
        }
        #expect(store.pixies.map(\.id) == ["a", "b", "new-2"])
    }

    /// The answer to the very save that changed the model decides the Auto notice, even
    /// while a later save still shows Auto.
    @Test func anUpdateAnswersWithTheDaemonsPixieForThatSave() async throws {
        let api = FakeAPI()
        var pixie = Self.pixies("a")[0]
        pixie.permissionMode = .auto
        api.set {
            $0.pixies = [pixie]
            $0.dropsAutoFor = ["haiku"]
        }
        let store = PixiesStore(api: api)
        try await store.load()

        let saved = try await store.update("a", UpdatePixieRequest(model: "haiku"))
        #expect(saved.permissionMode == .default)
        #expect(pixie.droppedAuto(by: UpdatePixieRequest(model: "haiku"), saved: saved))
    }

    /// Removing two chips quickly removes both: each change shows at once, saves run one
    /// after another, and a save's answer does not bring back a chip removed meanwhile.
    @Test func quickEditsBuildOnEachOther() async throws {
        let api = FakeAPI()
        var pixie = Self.pixies("a")[0]
        pixie.skills = ["x", "y", "z"]
        api.set { $0.pixies = [pixie] }
        let store = PixiesStore(api: api)
        try await store.load()
        let gate = AsyncStream.makeStream(of: Void.self)
        api.set { $0.gates["updatePixie"] = gate.stream }

        let first = Task { try await store.update("a", UpdatePixieRequest(skills: ["y", "z"])) }
        try await waitFor { api.calls.contains("updatePixie a") }
        #expect(store.pixies[0].skills == ["y", "z"])
        // The second list is built from what shows now.
        let next = store.pixies[0].skills.filter { $0 != "y" }
        let second = Task { try await store.update("a", UpdatePixieRequest(skills: next)) }
        try await Task.sleep(for: .milliseconds(20))
        #expect(api.calls.count { $0 == "updatePixie a" } == 1)
        #expect(store.pixies[0].skills == ["z"])
        // The first save's event and answer come while the second waits: the chip stays gone.
        var saved = pixie
        saved.skills = ["y", "z"]
        store.apply(pixieUpdated(saved))
        // An older one meanwhile does not replace it.
        var stale = saved
        stale.updatedAt = Date(timeIntervalSince1970: 0)
        store.apply(pixieUpdated(stale))
        #expect(store.pixies[0].skills == ["z"])

        gate.continuation.finish()
        try await first.value
        #expect(store.pixies[0].skills == ["z"])
        try await second.value
        #expect(api.calls.count { $0 == "updatePixie a" } == 2)
        #expect(store.pixies[0].skills == ["z"])
        #expect(api.state.withLock { $0.pixies[0].skills } == ["z"])
        #expect(!store.isSaving("a"))
    }

    /// A refused change goes back to what the daemon has.
    @Test func aRefusedChangeIsRolledBack() async throws {
        let api = FakeAPI()
        api.set { $0.pixies = Self.pixies("a") }
        api.fail("updatePixie", with: APIError.conflict("slug taken"))
        let store = PixiesStore(api: api)
        try await store.load()

        await #expect(throws: APIError.conflict("slug taken")) {
            try await store.update("a", UpdatePixieRequest(slug: "taken"))
        }
        #expect(store.pixies[0].slug == "a")
        // An unknown pixie is only sent.
        await #expect(throws: APIError.conflict("slug taken")) {
            try await store.update("x", UpdatePixieRequest(slug: "taken"))
        }
        #expect(store.pixies.map(\.id) == ["a"])
    }

    /// The daemon's answer wins once the saves are done, such as Auto dropping to Ask
    /// before edits after a model without Auto.
    @Test func theDaemonsAnswerWinsAtTheEnd() async throws {
        let api = FakeAPI()
        var pixie = Self.pixies("a")[0]
        pixie.permissionMode = .auto
        api.set {
            $0.pixies = [pixie]
            $0.dropsAutoFor = ["haiku"]
        }
        let store = PixiesStore(api: api)
        try await store.load()

        try await store.update("a", UpdatePixieRequest(model: "haiku"))
        #expect(store.pixies[0].model == "haiku")
        #expect(store.pixies[0].permissionMode == .default)
    }

    private func pixieUpdated(_ pixie: Pixie) -> Event {
        Fixture.event(EventType.pixieUpdated, #"{"pixie": \#(Fixture.json(pixie))}"#)
    }

    /// Every field a change names shows at once; Default clears the model and thinking.
    @Test func aChangeAppliesToThePixie() {
        let pixie = Self.pixies("a")[0]
        let changed = pixie.applying(
            UpdatePixieRequest(
                name: "N", slug: "n", mascot: .bluebell, color: "#000000", model: "opus",
                effort: .low, permissionMode: .plan, autonomy: .start, projectAccess: .noAccess,
                skills: ["s"], hidden: true))
        #expect(changed.name == "N")
        #expect(changed.slug == "n")
        #expect(changed.mascot == .bluebell)
        #expect(changed.color == "#000000")
        #expect(changed.model == "opus")
        #expect(changed.effort == .low)
        #expect(changed.permissionMode == .plan)
        #expect(changed.autonomy == .start)
        #expect(changed.projectAccess == .noAccess)
        #expect(changed.skills == ["s"])
        #expect(changed.hidden)
        #expect(changed.applying(UpdatePixieRequest()) == changed)
    }

    @Test func staleSavesSurfaceTheCurrentText() async throws {
        let api = FakeAPI()
        api.set { $0.staleFile = PixieFile(text: "theirs", hash: "h2") }
        let store = PixiesStore(api: api)

        await #expect(throws: APIError.staleFile(text: "theirs", hash: "h2")) {
            _ = try await store.save("p1", name: "soul", text: "mine", hash: "h1")
        }
    }

    @Test func createsUpdatesResetsAndDeletes() async throws {
        let api = FakeAPI()
        let store = PixiesStore(api: api)

        let created = try await store.create(CreatePixieRequest(name: "Watcher"))
        #expect(store.pixies.map(\.name) == ["Watcher"])
        try await store.update(created.id, UpdatePixieRequest(name: "Looker", hidden: true))
        #expect(store.pixies.map(\.name) == ["Looker"])
        #expect(store.visible.isEmpty)
        try await store.reset(created.id)
        try await store.delete(created.id)
        #expect(store.pixies.isEmpty)
        #expect(
            api.calls == [
                "createPixie Watcher", "updatePixie \(created.id)", "resetPixie \(created.id)",
                "deletePixie \(created.id)",
            ])
    }

    @Test func readsFilesNotesAndSearches() async throws {
        let api = FakeAPI()
        api.set {
            $0.pixieFiles = ["soul": PixieFile(text: "I am", hash: "h")]
            $0.pixieNotes = ["a", "b"]
            $0.pixieHits = [PixieSearchHit(file: "MEMORY.md", line: "- 2026-10-13: x")]
        }
        let store = PixiesStore(api: api)

        #expect(try await store.file("p1", name: "soul").text == "I am")
        #expect(try await store.notes("p1") == ["a", "b"])
        #expect(try await store.search("p1", query: "x").map(\.file) == ["MEMORY.md"])
        #expect(api.calls == ["pixieFile p1 soul", "pixieNotes p1", "searchPixie p1 x"])
    }

    @Test func requestsEncodeTheirFields() {
        let create = CreatePixieRequest(
            name: "A", slug: "a", mascot: .moth, color: "#E5484D", model: "opus", effort: .high,
            permissionMode: .plan, autonomy: .message, projectAccess: .read, skills: ["s"],
            hidden: true, soul: "Hi")
        #expect(
            Fixture.json(create)
                == ##"{"autonomy":"message","color":"#E5484D","effort":"high","hidden":true,"mascot":"moth","model":"opus","name":"A","permission_mode":"plan","project_access":"read","skills":["s"],"slug":"a","soul":"Hi"}"##
        )
        #expect(Fixture.json(CreatePixieRequest(name: "A")) == #"{"name":"A"}"#)
        #expect(Fixture.json(UpdatePixieRequest()) == "{}")
        // A key left out is unchanged; Model and Thinking are always real values (B94).
        #expect(Fixture.json(UpdatePixieRequest(model: "opus")) == #"{"model":"opus"}"#)
        #expect(Fixture.json(ReorderPixiesRequest(ids: ["b", "a"])) == #"{"ids":["b","a"]}"#)
        let full = UpdatePixieRequest(
            name: "N", slug: "n", mascot: .bluebell, color: "#000000", model: "m", effort: .low,
            permissionMode: .default, autonomy: .start, projectAccess: .noAccess, skills: [],
            hidden: false, teamID: "t1", maxRunning: 1, maxPerDay: 3)
        #expect(
            Fixture.json(full)
                == ##"{"autonomy":"start","color":"#000000","effort":"low","hidden":false,"mascot":"bluebell","max_per_day":3,"max_running":1,"model":"m","name":"N","permission_mode":"default","project_access":"none","skills":[],"slug":"n","team_id":"t1"}"##
        )
        #expect(
            Fixture.json(CreatePixieRequest(name: "A", projectAccess: .noAccess))
                == #"{"name":"A","project_access":"none"}"#)
        let none = Fixture.text("pixie").replacingOccurrences(of: "\"edit\"", with: "\"none\"")
        #expect(Fixture.decode(Pixie.self, json: none).projectAccess == .noAccess)
        #expect(
            Fixture.json(WritePixieFileRequest(text: "x", hash: nil))
                == #"{"hash":null,"text":"x"}"#)
        #expect(
            Fixture.json(WritePixieFileRequest(text: "x", hash: "h"))
                == #"{"hash":"h","text":"x"}"#)
    }

    /// B85 dropped a pixie's projects, backdrop, report level and tool rules; a pixie from a
    /// daemon that still sends them reads the same.
    @Test func anOlderPixieWithRemovedFieldsStillReads() {
        let older = Fixture.text("pixie").replacingOccurrences(
            of: #""skills": [],"#,
            with:
                #""skills": [], "background": "dusk", "projects": ["x"], "report_push": "info", "allowed_tools": ["A"], "disallowed_tools": [],"#
        )
        #expect(Fixture.decode(Pixie.self, json: older) == Fixture.decode(Pixie.self, "pixie"))
    }

    /// B89: the ten mascots of before read as the fairies that took their place, so a
    /// pixie or project saved by an older daemon keeps a sprite; only new names are written.
    @Test func oldMascotNamesReadAsTheirFairies() throws {
        let old = [
            "invader": Mascot.frost, "ghost": .brook, "cat": .bluebell, "owl": .moth,
            "robot": .star, "frog": .dragonfly, "mushroom": .rose, "bunny": .nightshade,
            "crab": .firefly, "sprout": .sprig,
        ]
        for (name, mascot) in old {
            let json = Fixture.text("pixie").replacingOccurrences(
                of: "\"sprig\"", with: "\"\(name)\"")
            #expect(Fixture.decode(Pixie.self, json: json).mascot == mascot)
        }
        for mascot in Mascot.choices {
            let decoded = try NestJSON.decoder.decode(
                Mascot.self, from: Data("\"\(mascot.rawValue)\"".utf8))
            #expect(decoded == mascot)
        }
        #expect(Fixture.json(UpdatePixieRequest(mascot: .frost)) == #"{"mascot":"frost"}"#)
    }

    @Test func unknownWireValuesReadAsUnknown() throws {
        var json = Fixture.text("pixie")
        json = json.replacingOccurrences(of: "\"sprig\"", with: "\"dragon\"")
            .replacingOccurrences(of: "\"observe\"", with: "\"roam\"")
            .replacingOccurrences(of: "\"edit\"", with: "\"admin\"")
        let pixie = Fixture.decode(Pixie.self, json: json)
        #expect(pixie.mascot == .unknown)
        #expect(pixie.autonomy == .unknown)
        #expect(pixie.projectAccess == .unknown)
        #expect(Mascot.allCases.count == 11)
    }
}
