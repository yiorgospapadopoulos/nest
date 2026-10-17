import Foundation
import Testing

@testable import NestKit

/// B79: artifacts the chats save, their events, how they read, the store behind the
/// Artifacts view and the badge, and their cards and tool calls in a transcript.
@MainActor @Suite struct ArtifactsTests {
    let api = FakeAPI()

    func store(_ artifacts: [Artifact] = [], unseen: Int = 0) -> ArtifactsStore {
        api.set {
            $0.artifacts = artifacts
            $0.unseenArtifacts = unseen
        }
        return ArtifactsStore(api: api)
    }

    static func savedEvent(_ artifact: String, version: Int = 1, unseen: Int = 1) -> Event {
        Fixture.event(
            EventType.artifactSaved,
            #"{"artifact": \#(artifact), "action": "updated", "version": \#(version), "unseen": \#(unseen)}"#,
            session: nil)
    }

    // MARK: Models and events

    @Test func anArtifactDecodesEveryField() {
        let artifact = Fixture.artifact(
            kind: "html", pixie: "p1", pixieName: "Reviewer", seen: true)
        #expect(artifact.id == "a1")
        #expect(artifact.title == "Options compared")
        #expect(artifact.kind == .html)
        #expect(artifact.repo == "cv-page")
        #expect(artifact.sessionID == "s1")
        #expect(artifact.chatTitle == "Pick a queue")
        #expect(!artifact.chatDeleted)
        #expect(artifact.pixieID == "p1")
        #expect(artifact.pixieName == "Reviewer")
        #expect(artifact.createdAt == Fixture.date("2026-10-17T09:30:00Z"))
        #expect(artifact.updatedAt == Fixture.date("2026-10-17T09:42:10Z"))
        #expect(artifact.latestVersion == 3)
        #expect(artifact.versionCount == 3)
        #expect(artifact.seen)
        #expect(Fixture.artifact(kind: "pdf").kind == .unknown)
        let made = Artifact(
            id: "a1", title: "Options compared", kind: .html, repo: "cv-page", sessionID: "s1",
            chatTitle: "Pick a queue", pixieID: "p1", pixieName: "Reviewer",
            createdAt: artifact.createdAt, updatedAt: artifact.updatedAt, latestVersion: 3,
            seen: true)
        #expect(made == artifact)
    }

    @Test func aDetailCarriesItsVersionsOldestFirst() {
        let detail = Fixture.detail(Fixture.artifact(latest: 2))
        #expect(detail.artifact.id == "a1")
        #expect(detail.versions.map(\.version) == [1, 2])
        #expect(detail.versions[0].title == "Options compared")
        #expect(detail.versions[0].size == 10)
        #expect(detail.versions[0].createdAt == Fixture.date("2026-10-17T09:30:00Z"))
    }

    @Test func versionContentDecodesAndMeasuresItsBytes() {
        let decoded = Fixture.decode(ArtifactContent.self, json: RouteCase.contentJSON)
        #expect(decoded.artifactID == "a1")
        #expect(decoded.version == 2)
        #expect(decoded.kind == .html)
        #expect(decoded.title == "Options compared")
        #expect(decoded.content == "<p>Hi</p>")
        #expect(decoded.size == 9)
        #expect(decoded.createdAt == Fixture.date("2026-10-17T09:41:00Z"))
        #expect(Fixture.content("a1", 1, "é").size == 2)
    }

    @Test func artifactEventsDecode() {
        let card = Fixture.event(
            EventType.sessionArtifact,
            #"{"artifact_id": "a1", "version": 2, "title": "Options", "kind": "html", "action": "updated"}"#
        )
        guard case .sessionArtifact(let body) = card.body else {
            Issue.record("not a card: \(card.body)")
            return
        }
        #expect(body.artifactID == "a1")
        #expect(body.version == 2)
        #expect(body.title == "Options")
        #expect(body.kind == .html)
        #expect(body.action == .updated)

        guard case .artifactSaved(let saved) = Self.savedEvent(Fixture.artifactJSON()).body else {
            Issue.record("not saved")
            return
        }
        #expect(saved.artifact == Fixture.artifact())
        #expect(saved.action == .updated)
        #expect(saved.version == 1)
        #expect(saved.unseen == 1)

        let seen = Fixture.event(
            EventType.artifactSeen, #"{"artifact_id": "a1", "unseen": 2}"#, session: nil)
        #expect(seen.body == .artifactSeen(id: "a1", unseen: 2))
        let gone = Fixture.event(
            EventType.artifactDeleted, #"{"artifact_id": "a1", "unseen": 0}"#, session: nil)
        #expect(gone.body == .artifactDeleted(id: "a1", unseen: 0))
    }

    // MARK: How they read

    @Test func theCSPGoesAheadOfEveryElement() {
        let meta = ArtifactHTML.meta
        #expect(
            meta
                == #"<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">"#
        )
        #expect(
            ArtifactHTML.sandboxed("<html><head><title>T</title></head></html>")
                == meta + "<html><head><title>T</title></head></html>")
        #expect(
            ArtifactHTML.sandboxed("\u{FEFF}<!DOCTYPE html>\n<!-- made by Claude -->\n<html>")
                == "\u{FEFF}<!DOCTYPE html>\n<!-- made by Claude -->\n" + meta + "<html>")
        // A comment or tag that mentions a head cannot hide the policy.
        #expect(
            ArtifactHTML.sandboxed("<!-- <head> --><p>Hi</p>")
                == "<!-- <head> -->" + meta + "<p>Hi</p>")
        #expect(ArtifactHTML.sandboxed("Plain text") == meta + "Plain text")
        #expect(ArtifactHTML.sandboxed("") == meta)
        // An unfinished comment or doctype ends the prelude where it starts.
        #expect(ArtifactHTML.sandboxed("<!-- open <p>") == meta + "<!-- open <p>")
        #expect(ArtifactHTML.sandboxed("  <!doctype html") == "  " + meta + "<!doctype html")
    }

    @Test func aTitleBecomesAFileName() {
        #expect(
            ArtifactFile.name(title: "Options compared", kind: .markdown) == "Options compared.md")
        #expect(ArtifactFile.name(title: "A/B: tests?  <v2>", kind: .html) == "A B tests v2.html")
        #expect(ArtifactFile.name(title: "..hidden. ", kind: .markdown) == "hidden.md")
        #expect(ArtifactFile.name(title: "\n\t", kind: .unknown) == "Artifact.txt")
        let long = String(repeating: "x", count: 300)
        #expect(ArtifactFile.name(title: long, kind: .html).count == 125)
    }

    @Test func theViewsWordsReadPlainly() {
        #expect(ArtifactText.origin(Fixture.artifact()) == "Pick a queue")
        #expect(ArtifactText.origin(Fixture.artifact(chatDeleted: true)) == "Deleted chat")
        #expect(ArtifactText.origin(Fixture.artifact(chatTitle: nil)) == "Deleted chat")
        #expect(
            ArtifactText.origin(Fixture.artifact(chatDeleted: true, pixieName: "Reviewer"))
                == "Reviewer")
        let now = Fixture.date("2026-10-17T10:00:00Z")
        #expect(ArtifactText.when(now - 20, now: now) == "now")
        #expect(ArtifactText.when(now - 540, now: now) == "9m ago")
        #expect(ArtifactText.kind(.markdown) == "Markdown")
        #expect(ArtifactText.kind(.html) == "HTML")
        #expect(ArtifactText.kind(.unknown) == "Document")
        #expect(ArtifactText.version(2, of: 3) == "Version 2 of 3")
        #expect(ArtifactText.empty(.chat("s1")) == "This chat has saved no artifacts yet.")
        #expect(
            ArtifactText.empty(.project("cv-page"))
                == "No chat in this project has saved an artifact yet.")
        #expect(ArtifactText.empty(.pixie("p1")) == "This pixie has saved no artifacts yet.")
        #expect(ArtifactText.empty(.pixies) == "No pixie has saved an artifact yet.")
        #expect(
            [ArtifactQuery.chat("s1"), .project("r"), .pixie("p"), .pixies].map(\.label) == [
                "This chat", "Whole project", "This pixie", "All pixies",
            ])
        #expect(ArtifactText.deleted == "Deleted")
        #expect([0, -1, 1, 99, 100].map(ArtifactText.badge) == [nil, nil, "1", "99", "99+"])
    }

    @Test func aCardSaysSavedOrItsVersion() {
        func card(_ action: String, _ version: Int) -> ArtifactCard {
            Fixture.decode(
                ArtifactCard.self,
                json:
                    #"{"artifact_id": "a1", "version": \#(version), "title": "T", "kind": "markdown", "action": "\#(action)"}"#
            )
        }
        #expect(ArtifactText.cardState(card("created", 1)) == "Saved")
        #expect(ArtifactText.cardState(card("updated", 3)) == "Version 3")
        #expect(card("renamed", 2).action == .unknown)
        #expect(ArtifactText.cardState(card("renamed", 2)) == "Saved")
    }

    @Test func queriesMatchTheirArtifacts() {
        let chat = Fixture.artifact()
        let pixie = Fixture.artifact(repo: "pixie:p1", session: "pc", pixie: "p1")
        #expect(ArtifactQuery.chat("s1").matches(chat))
        #expect(!ArtifactQuery.chat("s2").matches(chat))
        #expect(ArtifactQuery.project("cv-page").matches(chat))
        #expect(!ArtifactQuery.project("cv-page").matches(pixie))
        #expect(ArtifactQuery.pixie("p1").matches(pixie))
        #expect(!ArtifactQuery.pixie("p1").matches(chat))
        #expect(ArtifactQuery.pixies.matches(pixie))
        #expect(!ArtifactQuery.pixies.matches(chat))
    }

    @Test func theSwitchOffersEachTabsViews() {
        #expect(ProjectView.choices(pixies: false) == [.workspace, .board, .artifacts])
        #expect(ProjectView.choices(pixies: true) == [.workspace, .artifacts])
        #expect(ProjectView.allTitles == ["Workspace", "Board", "Artifacts"])
    }

    // MARK: Store

    @Test func listsLoadByTheirFiltersNewestFirst() async throws {
        let store = store(
            [
                Fixture.artifact(id: "a2"), Fixture.artifact(id: "a1", session: "s2"),
                Fixture.artifact(id: "p", repo: "pixie:p1", session: "pc", pixie: "p1"),
            ], unseen: 3)
        #expect(store.list(.chat("s1")) == nil)
        try await store.load(.chat("s1"))
        try await store.load(.project("cv-page"))
        try await store.load(.pixie("p1"))
        try await store.load(.pixies)
        try await store.loadUnseen()
        #expect(
            api.calls == [
                "artifacts session=s1", "artifacts repo=cv-page", "artifacts pixie=p1",
                "artifacts", "unseenArtifacts",
            ])
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a2"])
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a2", "a1"])
        #expect(store.list(.pixie("p1"))?.map(\.id) == ["p"])
        // The daemon lists every artifact without a filter; only pixies' are kept.
        #expect(store.list(.pixies)?.map(\.id) == ["p"])
        #expect(store.unseen == 3)
        #expect(store.artifact("a1")?.sessionID == "s2")
        #expect(store.availability(of: "a1") == .available)
        #expect(store.availability(of: "zz") == .unknown)
    }

    @Test func theViewStartsNarrowAndSwitchesWide() async throws {
        let store = store([
            Fixture.artifact(id: "a2", session: "s2"), Fixture.artifact(id: "a1"),
        ])
        api.set {
            $0.artifactContents = [
                "a1/3": Fixture.content("a1", 3), "a2/3": Fixture.content("a2", 3),
            ]
        }
        #expect(store.query == nil)
        try await store.open()
        try await store.setWide(true)
        #expect(store.selection == nil)
        #expect(api.calls.isEmpty)

        store.show(ArtifactScope(narrow: .chat("s1"), wide: .project("cv-page")))
        #expect(store.query == .chat("s1"))
        try await store.open()
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a1"])
        // The newest opens in the reader, at its latest version, which marks it seen.
        #expect(store.selection == ArtifactSelection(id: "a1", version: 3))
        #expect(store.selected?.seen == true)
        #expect(store.selectedContent?.artifactID == "a1")

        try await store.setWide(true)
        #expect(store.query == .project("cv-page"))
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a2", "a1"])
        #expect(store.selection?.id == "a1")
        try await store.setWide(false)
        #expect(store.query == .chat("s1"))
        #expect(api.calls.filter { $0.hasPrefix("artifacts") }.count == 2)

        // The same scope again keeps the switch; another scope starts narrow.
        try await store.setWide(true)
        store.show(ArtifactScope(narrow: .chat("s1"), wide: .project("cv-page")))
        #expect(store.showsWide)
        store.show(ArtifactScope(narrow: .chat("s2"), wide: .project("cv-page")))
        #expect(!store.showsWide)
        #expect(store.query == .chat("s2"))
        // A narrow list without the selection moves it to its newest.
        try await store.setWide(false)
        #expect(store.selection?.id == "a2")

        store.show(ArtifactScope(narrow: nil, wide: .pixies))
        #expect(store.query == .pixies)
        try await store.open()
        #expect(store.list(.pixies)?.isEmpty == true)
        #expect(store.selection == nil)
    }

    @Test func stepsThroughVersionsAndMarksOnlyTheLatestSeen() async throws {
        let store = store([Fixture.artifact(latest: 3)], unseen: 2)
        try await store.loadUnseen()
        api.set {
            $0.artifactContents = [
                "a1/1": Fixture.content("a1", 1, "one"), "a1/2": Fixture.content("a1", 2, "two"),
                "a1/3": Fixture.content("a1", 3, "three"),
            ]
        }
        #expect(!store.canStep(by: 1))
        try await store.step(by: 1)
        try await store.select("a1", version: 2)
        #expect(store.selectedContent?.content == "two")
        #expect(store.selected?.seen == false)
        #expect(store.canStep(by: -1))
        #expect(store.canStep(by: 1))
        #expect(!store.canStep(by: 2))
        try await store.step(by: -1)
        #expect(store.selection?.version == 1)
        try await store.step(by: -1)
        #expect(store.selection?.version == 1)
        try await store.step(by: 2)
        #expect(store.selectedContent?.content == "three")
        #expect(store.selected?.seen == true)
        #expect(store.unseen == 1)
        #expect(api.calls.filter { $0.hasPrefix("markArtifactSeen") } == ["markArtifactSeen a1"])
        // Read versions are kept; out of range versions show the nearest.
        try await store.select("a1", version: 9)
        try await store.select("a1", version: 0)
        #expect(store.selection?.version == 1)
        #expect(api.calls.filter { $0.hasPrefix("artifactContent") }.count == 3)
        #expect(store.content(ArtifactSelection(id: "a1", version: 2))?.content == "two")
    }

    @Test func anArtifactOpenedFromACardIsReadFirst() async throws {
        let store = store([Fixture.artifact(id: "a9", latest: 2, seen: true)])
        api.set { $0.artifactContents = ["a9/1": Fixture.content("a9", 1)] }
        try await store.select("a9", version: 1)
        #expect(api.calls == ["artifact a9", "artifactContent a9/1"])
        #expect(store.selected?.id == "a9")

        await #expect(throws: APIError.notFound("artifact not found")) {
            try await store.select("gone")
        }
        #expect(store.availability(of: "gone") == .deleted)
        #expect(store.selection?.id == "a9")
    }

    @Test func aFailedSeenMarkLeavesItUnseen() async throws {
        let store = store([Fixture.artifact(latest: 1)], unseen: 1)
        try await store.loadUnseen()
        api.set { $0.artifactContents = ["a1/1": Fixture.content("a1", 1)] }
        api.fail("markArtifactSeen")
        try await store.select("a1")
        #expect(store.selected?.seen == false)
        #expect(store.unseen == 1)
    }

    @Test func aSeenEventFirstIsNotCountedTwice() async throws {
        let store = store([Fixture.artifact(latest: 1)], unseen: 2)
        try await store.loadUnseen()
        try await store.load(.project("cv-page"))
        store.apply(
            Fixture.event(
                EventType.artifactSeen, #"{"artifact_id": "a1", "unseen": 1}"#, session: nil))
        api.set { $0.artifactContents = ["a1/1": Fixture.content("a1", 1)] }
        try await store.select("a1")
        #expect(store.unseen == 1)
        #expect(api.calls.contains("markArtifactSeen a1") == false)
    }

    @Test func cardsLearnOnceWhetherTheirArtifactIsThere() async throws {
        let store = store([Fixture.artifact(id: "a1")])
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["artifact"] = gate.stream }
        let first = Task { await store.check("a1") }
        let second = Task { await store.check("a1") }
        try await waitFor { api.calls.count == 1 }
        gate.continuation.finish()
        await first.value
        await second.value
        #expect(api.calls == ["artifact a1"])
        #expect(store.availability(of: "a1") == .available)
        await store.check("a1")
        #expect(api.calls.count == 1)

        api.set { $0.gates = [:] }
        await store.check("gone")
        #expect(store.availability(of: "gone") == .deleted)
        api.fail("artifact")
        await store.check("other")
        #expect(store.availability(of: "other") == .unknown)
    }

    @Test func deletingRemovesItEverywhere() async throws {
        let store = store([Fixture.artifact(id: "a2"), Fixture.artifact(id: "a1", seen: true)])
        api.set { $0.artifactContents = ["a2/3": Fixture.content("a2", 3)] }
        store.show(ArtifactScope(narrow: nil, wide: .project("cv-page")))
        try await store.open()
        try await store.load(.chat("s1"))
        #expect(store.selection?.id == "a2")
        api.set { $0.unseenArtifacts = 4 }
        try await store.loadUnseen()

        api.set { $0.artifactContents["a1/3"] = Fixture.content("a1", 3) }
        try await store.delete("a2")
        #expect(api.calls.contains("deleteArtifact a2"))
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a1"])
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a1"])
        #expect(store.availability(of: "a2") == .deleted)
        #expect(store.content(ArtifactSelection(id: "a2", version: 3)) == nil)
        // The next one opens; it was seen, so the count only lost the deleted one.
        #expect(store.selection?.id == "a1")
        #expect(store.unseen == 4)

        api.fail("deleteArtifact")
        await #expect(throws: APIError.self) { try await store.delete("a1") }
        #expect(store.artifact("a1") != nil)
    }

    @Test func deletingAnUnseenOneLowersTheCount() async throws {
        let store = store([Fixture.artifact(id: "a1")], unseen: 1)
        try await store.loadUnseen()
        try await store.load(.chat("s1"))
        try await store.delete("a1")
        #expect(store.unseen == 0)
        #expect(store.selection == nil)
    }

    @Test func savedEventsMoveItToTheTopOfTheListsItMatches() async throws {
        let store = store([Fixture.artifact(id: "a2"), Fixture.artifact(id: "a1", session: "s2")])
        try await store.load(.project("cv-page"))
        try await store.load(.chat("s2"))
        try await store.load(.pixie("p1"))
        store.apply(
            Self.savedEvent(
                Fixture.artifactJSON(id: "a1", title: "New title", session: "s2", latest: 4),
                version: 4, unseen: 5))
        #expect(store.unseen == 5)
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a1", "a2"])
        #expect(store.list(.chat("s2"))?.map(\.id) == ["a1"])
        #expect(store.list(.pixie("p1"))?.isEmpty == true)
        #expect(store.artifact("a1")?.title == "New title")
        #expect(store.artifact("a1")?.latestVersion == 4)

        store.apply(Self.savedEvent(Fixture.artifactJSON(id: "a3"), unseen: 6))
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a3", "a1", "a2"])
        #expect(store.list(.chat("s2"))?.map(\.id) == ["a1"])
    }

    @Test func seenDeletedAndGoneChatEventsPatchTheStore() async throws {
        let store = store([
            Fixture.artifact(id: "a1"), Fixture.artifact(id: "a2", session: "s2"),
            Fixture.artifact(id: "p", repo: "pixie:p1", session: "pc", pixie: "p1"),
        ])
        api.set { $0.artifactContents = ["a1/3": Fixture.content("a1", 3)] }
        try await store.load(.project("cv-page"))
        try await store.load(.pixies)
        store.apply(
            Fixture.event(
                EventType.artifactSeen, #"{"artifact_id": "a2", "unseen": 7}"#, session: nil))
        #expect(store.artifact("a2")?.seen == true)
        #expect(store.unseen == 7)

        store.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#))
        #expect(store.artifact("a1")?.chatDeleted == true)
        #expect(store.artifact("a2")?.chatDeleted == false)
        store.apply(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p1"}"#))
        #expect(store.artifact("p")?.chatDeleted == true)

        try await store.select("a1")
        store.apply(
            Fixture.event(
                EventType.artifactDeleted, #"{"artifact_id": "a1", "unseen": 2}"#, session: nil))
        #expect(store.unseen == 2)
        #expect(store.selection == nil)
        #expect(store.artifact("a1") == nil)
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a2"])
        #expect(store.list(.pixies)?.map(\.id) == ["p"])

        store.apply(Fixture.event(EventType.notify, "{}"))
        #expect(store.unseen == 2)
    }

    @Test func aReloadReadsTheCountTheListsAndTheOpenOne() async throws {
        let store = store([Fixture.artifact(id: "a1"), Fixture.artifact(id: "a2")])
        api.set { $0.artifactContents = ["a1/3": Fixture.content("a1", 3)] }
        try await store.load(.chat("s1"))
        try await store.select("a1")
        api.set {
            $0.artifacts = [Fixture.artifact(id: "a3"), Fixture.artifact(id: "a1")]
            $0.unseenArtifacts = 9
        }
        try await store.reload()
        #expect(store.unseen == 9)
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a3", "a1"])
        #expect(api.calls.suffix(3) == ["unseenArtifacts", "artifacts session=s1", "artifact a1"])

        // The open one was deleted while away: the reader leaves it.
        api.set { $0.artifacts = [] }
        try await store.reload()
        #expect(store.selection == nil)
        #expect(store.availability(of: "a1") == .deleted)
    }

    @Test func liveSyncLoadsAndRoutesArtifacts() async throws {
        let model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        api.set { $0.unseenArtifacts = 4 }
        await model.live.refresh()
        #expect(model.artifacts.unseen == 4)
        model.live.route(
            Fixture.event(
                EventType.artifactSeen, #"{"artifact_id": "a1", "unseen": 3}"#, session: nil))
        #expect(model.artifacts.unseen == 3)
    }

    // MARK: Transcript

    @Test func aSavedArtifactIsACardAndItsCallHides() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let input = ##"{"title": "Plan", "kind": "markdown", "content": "# A long document"}"##
        let events = [
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_use", "id": "t1", "name": "mcp__nest__create_artifact", "input": \#(input)}]}"#,
                id: 1),
            Fixture.event(
                EventType.sessionArtifact,
                #"{"artifact_id": "a1", "version": 1, "title": "Plan", "kind": "markdown", "action": "created"}"#,
                id: 2),
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_use", "id": "t2", "name": "mcp__nest__update_artifact", "input": {"artifact_id": "x", "content": "y"}}]}"#,
                id: 3),
        ]
        for event in events {
            transcript.receive(event)
        }
        // While it runs, the call shows, by its title and never its content.
        #expect(transcript.visibleItems.map(\.id) == ["t1", "e2", "t2"])
        guard case .tool(let call) = transcript.visibleItems[0].content,
            case .artifact(let card) = transcript.visibleItems[1].content
        else {
            Issue.record("not a call and a card")
            return
        }
        #expect(card.artifactID == "a1")
        #expect(ToolSummary.kind(of: call.name) == .artifact)
        #expect(ToolSummary.name(of: call.name) == "Save artifact")
        #expect(ToolSummary.name(of: ArtifactTools.update) == "Update artifact")
        #expect(ToolSummary.name(of: "Read") == "Read")
        #expect(ToolSummary.argument(of: call) == "Plan")
        #expect(ToolSummary.argument(tool: ArtifactTools.update, input: .object([:])) == "")
        #expect(ArtifactTools.contains(ArtifactTools.create))
        #expect(!ArtifactTools.contains("Write"))

        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_result", "tool_use_id": "t1", "content": "Saved artifact a1 (version 1): Plan."}, {"type": "tool_result", "tool_use_id": "t2", "content": "unknown artifact 'x'", "is_error": true}]}"#,
                id: 4))
        // Saved: the card says it. Refused: the call stays to read why.
        #expect(transcript.visibleItems.map(\.id) == ["e2", "t2"])
    }

    @Test func artifactCallsReadAsSavesInSummaries() {
        let input = JSONValue.object(["title": .string("Plan")])
        let calls = [
            ToolCall(
                id: "1", name: ArtifactTools.create, input: input, result: nil, isError: false),
            ToolCall(
                id: "2", name: ArtifactTools.update, input: input, result: "ok", isError: false),
        ]
        #expect(ToolActivity.summary(calls, running: true) == "Saving 2 artifacts")
        #expect(ToolActivity.summary(Array(calls.prefix(1)), running: false) == "Saved 1 artifact")
        let step = CallStep(id: "s", kind: .tool(name: ArtifactTools.create, input: input))
        #expect(step.line == "Save artifact Plan")
    }

    @Test func thePaletteOffersTheArtifactsView() {
        let app = AppStore(api: api, store: MemoryStore())
        let sessions = SessionsStore(api: api, approvals: ApprovalsStore(api: api))
        app.openProject("cv-page")
        func titles() -> [String] {
            CommandPalette.catalog(app: app, sessions: sessions).items.map(\.title)
        }
        #expect(titles().contains("Show the Artifacts view"))
        let item = CommandPalette.catalog(app: app, sessions: sessions).items.first {
            $0.title == "Show the Artifacts view"
        }
        #expect(item?.action == .showView(.artifacts))
        #expect(item?.glyph == .artifacts)
        app.update { $0.view = .artifacts }
        #expect(!titles().contains("Show the Artifacts view"))
        #expect(titles().contains("Show the Workspace view"))
    }
}

extension ProjectView {
    fileprivate static var allTitles: [String] {
        choices(pixies: false).map(\.title)
    }
}
