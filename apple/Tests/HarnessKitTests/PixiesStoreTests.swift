import Foundation
import Testing

@testable import HarnessKit

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
                ##"{"pixie": {"id": "p1", "slug": "tester", "name": "QA", "mascot": "sprout", "##
                    + ##""color": "#8B7CF6", "background": "plain", "model": null, "effort": null, "##
                    + ##""permission_mode": "default", "autonomy": "observe", "project_access": "edit", "##
                    + ##""projects": null, "skills": [], "can_call": [], "allowed_tools": [], "##
                    + ##""disallowed_tools": [], "hidden": false, "##
                    + ##""position": 0, "chat_session_id": null, "##
                    + ##""created_at": "2026-10-13T09:00:00Z", "updated_at": "2026-10-13T09:00:00Z"}}"##
            ))
        store.apply(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p2"}"#))
        #expect(store.pixies.map(\.name) == ["QA"])
        store.apply(Fixture.event(EventType.sessionCreated, #"{"session": null}"#))
        #expect(store.pixies.count == 1)
    }

    @Test func sendsAndSaves() async throws {
        let api = FakeAPI()
        let store = PixiesStore(api: api)

        _ = try await store.send("p1", text: "hi")
        _ = try await store.save("p1", name: "soul", text: "x", hash: "h")
        #expect(api.calls == ["sendToPixie p1", "savePixieFile p1 soul"])
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
            name: "A", slug: "a", mascot: .owl, color: "#E5484D", background: .dusk,
            model: "opus", effort: .high, permissionMode: .plan, autonomy: .message,
            projectAccess: .read, projects: ["x"], skills: ["s"], allowedTools: ["Bash(ls:*)"],
            disallowedTools: ["Edit"], hidden: true, soul: "Hi")
        #expect(
            Fixture.json(create)
                == ##"{"allowed_tools":["Bash(ls:*)"],"autonomy":"message","background":"dusk","color":"#E5484D","disallowed_tools":["Edit"],"effort":"high","hidden":true,"mascot":"owl","model":"opus","name":"A","permission_mode":"plan","project_access":"read","projects":["x"],"skills":["s"],"slug":"a","soul":"Hi"}"##
        )
        #expect(Fixture.json(CreatePixieRequest(name: "A")) == #"{"name":"A"}"#)
        #expect(
            Fixture.json(UpdatePixieRequest(name: "B", allProjects: true))
                == #"{"all_projects":true,"name":"B"}"#)
        #expect(Fixture.json(UpdatePixieRequest()) == "{}")
        let full = UpdatePixieRequest(
            name: "N", slug: "n", mascot: .cat, color: "#000000", background: .night,
            model: "m", effort: .low, permissionMode: .default, autonomy: .start,
            projectAccess: .noAccess, projects: [], skills: [], allowedTools: [],
            disallowedTools: [], hidden: false, allProjects: false)
        #expect(Fixture.json(full).contains(#""project_access":"none""#))
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

    @Test func unknownWireValuesReadAsUnknown() throws {
        var json = Fixture.text("pixie")
        json = json.replacingOccurrences(of: "\"sprout\"", with: "\"dragon\"")
            .replacingOccurrences(of: "\"plain\"", with: "\"aurora\"")
            .replacingOccurrences(of: "\"observe\"", with: "\"roam\"")
            .replacingOccurrences(of: "\"edit\"", with: "\"admin\"")
        let pixie = Fixture.decode(Pixie.self, json: json)
        #expect(pixie.mascot == .unknown)
        #expect(pixie.background == .unknown)
        #expect(pixie.autonomy == .unknown)
        #expect(pixie.projectAccess == .unknown)
        #expect(Mascot.allCases.count == 11)
    }
}
