import Foundation
import Testing

@testable import NestKit

/// B88 stage 3: what an artifact page stores, its files, the files it offers to save, and
/// the storage changes made elsewhere that reach the open page.
@MainActor @Suite struct ArtifactPageDataTests {
    let api = FakeAPI()

    static func request(_ method: String, _ params: Any) -> [String: Any] {
        ["nest": 1, "id": "r1", "method": method, "params": params]
    }

    static func failure(_ message: ArtifactBridge.Message) -> ArtifactBridge.Code? {
        ArtifactBridgeTests.failure(message)
    }

    static func code(_ reply: ArtifactBridge.Reply?) -> ArtifactBridge.Code? {
        ArtifactBridgeTests.code(reply)
    }

    static func message(_ reply: ArtifactBridge.Reply?) -> String? {
        if case .failure(let failure) = reply?.outcome {
            return failure.message
        }
        return nil
    }

    // MARK: Models and events

    @Test func storageAndItsChangesDecode() {
        let storage = Fixture.decode(
            ArtifactStorage.self, json: #"{"items": {"done": "1", "note": "hi"}, "size": 12}"#)
        #expect(storage.items == ["done": "1", "note": "hi"])
        #expect(storage.size == 12)

        let written = Fixture.event(
            EventType.artifactStorage,
            #"{"artifact_id": "a1", "set": {"done": "2"}, "remove": ["note"], "clear": false}"#,
            session: nil)
        #expect(
            written.body
                == .artifactStorage(
                    ArtifactStorageEvent(
                        artifactID: "a1", change: .write(set: ["done": "2"], remove: ["note"]))))
        let cleared = Fixture.event(
            EventType.artifactStorage,
            #"{"artifact_id": "a1", "set": {}, "remove": [], "clear": true}"#, session: nil)
        #expect(
            cleared.body
                == .artifactStorage(ArtifactStorageEvent(artifactID: "a1", change: .clear)))
        let removal = Fixture.event(
            EventType.artifactStorage, #"{"artifact_id": "a1", "remove": ["k"]}"#, session: nil)
        #expect(
            removal.body
                == .artifactStorage(
                    ArtifactStorageEvent(artifactID: "a1", change: .write(set: [:], remove: ["k"])))
        )
        let sparse = Fixture.event(
            EventType.artifactStorage, #"{"artifact_id": "a1", "set": {"k": "v"}}"#,
            session: nil)
        #expect(
            sparse.body
                == .artifactStorage(
                    ArtifactStorageEvent(
                        artifactID: "a1", change: .write(set: ["k": "v"], remove: []))
                ))
    }

    @Test func aVersionListsItsFiles() {
        let json =
            String(RouteCase.contentJSON.dropLast())
            + #", "files": [{"path": "app.js", "size": 120, "mime": "text/javascript"}]}"#
        let content = Fixture.decode(ArtifactContent.self, json: json)
        #expect(
            content.files == [ArtifactFileInfo(path: "app.js", size: 120, mime: "text/javascript")])
        #expect(Fixture.decode(ArtifactContent.self, json: RouteCase.contentJSON).files.isEmpty)
    }

    @Test func savingAMultiFilePageWritesTheBuiltPage() {
        let files = [ArtifactFileInfo(path: "app.js", size: 3, mime: "text/javascript")]
        func content(_ kind: ArtifactKind, files: [ArtifactFileInfo]) -> ArtifactContent {
            ArtifactContent(
                artifactID: "a1", version: 1, kind: kind, title: "T", content: "<p>src</p>",
                page: "<!doctype html><p>built</p>",
                createdAt: Fixture.date("2026-10-17T09:30:00Z"),
                files: files)
        }
        #expect(
            ArtifactFile.savedText(content(.html, files: files)) == "<!doctype html><p>built</p>")
        #expect(ArtifactFile.savedText(content(.html, files: [])) == "<p>src</p>")
        #expect(ArtifactFile.savedText(content(.document, files: files)) == "<p>src</p>")
    }

    @Test func theLineNamesWhatThePageStored() {
        let now = Fixture.date("2026-10-17T10:00:00Z")
        let artifact = Fixture.artifact(kind: "html")
        #expect(
            ArtifactText.line(artifact, author: .agent, saved: now, now: now, stored: 12_000)
                == "HTML · Pick a queue · saved now · 12 KB stored")
        #expect(
            ArtifactText.line(artifact, author: .agent, saved: now, now: now, stored: 0)
                == "HTML · Pick a queue · saved now")
    }

    // MARK: Parsing

    @Test func storageWriteTakesStringsAndKeysOfAFairLength() {
        #expect(
            ArtifactBridge.parse(
                Self.request("storageWrite", ["set": ["a": "1"], "remove": ["b"]]))
                == .call(id: "r1", .storage(.write(set: ["a": "1"], remove: ["b"]))))
        #expect(
            ArtifactBridge.parse(Self.request("storageWrite", [:]))
                == .call(id: "r1", .storage(.write(set: [:], remove: []))))
        let longest = String(repeating: "k", count: 256)
        #expect(
            Self.failure(
                ArtifactBridge.parse(Self.request("storageWrite", ["set": [longest: "v"]])))
                == nil)
        for params: [String: Any] in [
            ["set": ["a": 1]], ["set": "a"], ["remove": "a"], ["remove": [1]], ["set": ["": "v"]],
            ["set": [longest + "k": "v"]], ["remove": [""]],
        ] {
            #expect(
                Self.failure(ArtifactBridge.parse(Self.request("storageWrite", params)))
                    == .badRequest, "\(params)")
        }
        let big = String(repeating: "v", count: 256 * 1024 + 1)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("storageWrite", ["set": ["k": big]])))
                == .quota)
        let fits = String(repeating: "v", count: 256 * 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("storageWrite", ["set": ["k": fits]])))
                == nil)
        #expect(
            ArtifactBridge.parse(Self.request("storageClear", [:]))
                == .call(id: "r1", .storage(.clear)))
    }

    @Test func storageWriteAndSaveFileHaveTheirOwnSizeLimits() {
        let mebibyte = String(repeating: "v", count: 200 * 1024)
        let items = Dictionary(uniqueKeysWithValues: (0..<10).map { ("k\($0)", mebibyte) })
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("storageWrite", ["set": items]))) == nil)
        let over = Dictionary(uniqueKeysWithValues: (0..<11).map { ("k\($0)", mebibyte) })
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("storageWrite", ["set": over])))
                == .tooLarge)
        let file = String(repeating: "a", count: 20 * 1024 * 1024)
        #expect(
            Self.failure(
                ArtifactBridge.parse(Self.request("saveFile", ["name": "a.txt", "content": file])))
                == nil)
        let tooBig = String(repeating: "a", count: 24 * 1024 * 1024)
        #expect(
            Self.failure(
                ArtifactBridge.parse(
                    Self.request("saveFile", ["name": "a.txt", "content": tooBig])))
                == .tooLarge)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request("storageClear", ["x": mebibyte])))
                == .tooLarge)
    }

    @Test func saveFileTakesANameAndTextOrBase64() {
        #expect(
            ArtifactBridge.parse(
                Self.request(
                    "saveFile",
                    ["name": "habits.csv", "content": "a,b\n", "mime": "text/csv"]))
                == .call(id: "r1", .saveFile(name: "habits.csv", data: Data("a,b\n".utf8))))
        #expect(
            ArtifactBridge.parse(
                Self.request(
                    "saveFile", ["name": "a/b:c.png", "content": "AAEC", "encoding": "base64"]))
                == .call(id: "r1", .saveFile(name: "a b c.png", data: Data([0, 1, 2]))))
        #expect(
            ArtifactBridge.parse(
                Self.request("saveFile", ["name": "x.txt", "content": "y", "encoding": "utf8"]))
                == .call(id: "r1", .saveFile(name: "x.txt", data: Data("y".utf8))))
        for params: [String: Any] in [
            [:], ["name": "a.txt"], ["content": "x"], ["name": 3, "content": "x"],
            ["name": "a.txt", "content": 3], ["name": "a.txt", "content": "x", "encoding": "hex"],
            ["name": "a.txt", "content": "not base64!", "encoding": "base64"],
            ["name": "a.txt", "content": "x", "mime": 4], ["name": " / ", "content": "x"],
        ] {
            #expect(
                Self.failure(ArtifactBridge.parse(Self.request("saveFile", params))) == .badRequest,
                "\(params)")
        }
        #expect(ArtifactBridge.Code.quota.rawValue == "quota")
    }

    // MARK: The session

    final class Writes {
        var made: [ArtifactStorageChange] = []
        var failure: (any Error)?
        var saved: [(String, Data)] = []
        var answer = true
    }

    static func session(_ writes: Writes) -> ArtifactBridgeSession {
        ArtifactBridgeSession(
            prompt: ArtifactLinkPrompt(),
            storage: { change in
                if let failure = writes.failure {
                    throw failure
                }
                writes.made.append(change)
                return change == .clear ? 0 : 7
            },
            saveFile: { name, data in
                writes.saved.append((name, data))
                return writes.answer
            }
        ) { _ in }
    }

    @Test func storageWritesGoThroughAndTheirFailuresAreNamed() async {
        let writes = Writes()
        let session = Self.session(writes)
        let write = Self.request("storageWrite", ["set": ["a": "1"], "remove": ["b"]])
        #expect(
            await session.receive(write)
                == ArtifactBridge.Reply("r1", .success(.object(["size": .number(7)]))))
        #expect(
            await session.receive(Self.request("storageClear", [:]))?.outcome
                == .success(.object(["size": .number(0)])))
        #expect(writes.made == [.write(set: ["a": "1"], remove: ["b"]), .clear])

        writes.failure = APIError.payloadTooLarge("Storage is over 2 MiB.")
        let full = await session.receive(write)
        #expect(Self.code(full) == .quota)
        #expect(Self.message(full) == "Storage is over 2 MiB.")
        writes.failure = APIError.invalidInput("Bad key")
        #expect(Self.code(await session.receive(write)) == .badRequest)
        writes.failure = APIError.transport("offline")
        #expect(Self.code(await session.receive(write)) == .unavailable)

        let none = ArtifactBridgeSession(prompt: ArtifactLinkPrompt()) { _ in }
        #expect(Self.code(await none.receive(write)) == .unavailable)
        #expect(
            Self.code(await none.receive(Self.request("saveFile", ["name": "a", "content": "b"])))
                == .unavailable)
    }

    @Test func saveFileAsksAndRepliesOrDeclines() async {
        let writes = Writes()
        let session = Self.session(writes)
        let request = Self.request("saveFile", ["name": "a.csv", "content": "x"])
        #expect(
            await session.receive(request)
                == ArtifactBridge.Reply("r1", .success(.object(["saved": .bool(true)]))))
        writes.answer = false
        #expect(Self.code(await session.receive(request)) == .declined)
        #expect(writes.saved.map(\.0) == ["a.csv", "a.csv"])
        #expect(writes.saved.map(\.1) == [Data("x".utf8), Data("x".utf8)])
    }

    @Test func changesFromElsewhereBecomeHostEventsButThePagesOwnEchoesDoNot() async {
        let writes = Writes()
        let session = Self.session(writes)
        let mine = ArtifactStorageChange.write(set: ["a": "1"], remove: [])
        _ = await session.receive(Self.request("storageWrite", ["set": ["a": "1"]]))
        // Another device's change goes in; this page's own write comes back once and is skipped.
        let other = ArtifactStorageChange.write(set: ["b": "2", "a": "0"], remove: ["c"])
        #expect(
            session.hostEvents(for: other) == [
                .object([
                    "nest": .number(1), "event": .string("storage"), "key": .string("a"),
                    "value": .string("0"),
                ]),
                .object([
                    "nest": .number(1), "event": .string("storage"), "key": .string("b"),
                    "value": .string("2"),
                ]),
                .object([
                    "nest": .number(1), "event": .string("storage"), "key": .string("c"),
                    "value": .null,
                ]),
            ])
        #expect(session.hostEvents(for: mine).isEmpty)
        #expect(session.hostEvents(for: mine).count == 1)
        #expect(
            session.hostEvents(for: .clear) == [
                .object(["nest": .number(1), "event": .string("storage"), "clear": .bool(true)])
            ])
        _ = await session.receive(Self.request("storageClear", [:]))
        #expect(session.hostEvents(for: .clear).isEmpty)

        // A failed write is not waited for.
        writes.failure = APIError.transport("offline")
        _ = await session.receive(Self.request("storageWrite", ["set": ["z": "9"]]))
        #expect(session.hostEvents(for: .write(set: ["z": "9"], remove: [])).count == 1)
    }

    @Test func onlyTheLatestOwnWritesAreRemembered() async {
        var now = Date(timeIntervalSince1970: 0)
        let session = ArtifactBridgeSession(
            prompt: ArtifactLinkPrompt(), now: { now }, storage: { _ in 1 }
        ) { _ in }
        for index in 0..<60 {
            now = now.addingTimeInterval(1)
            _ = await session.receive(Self.request("storageWrite", ["set": ["k": "\(index)"]]))
        }
        #expect(session.hostEvents(for: .write(set: ["k": "0"], remove: [])).count == 1)
        #expect(session.hostEvents(for: .write(set: ["k": "59"], remove: [])).isEmpty)
    }

    @Test func aHostEventIsAScriptCallingTheShim() throws {
        let event = ArtifactBridge.Value.object([
            "nest": .number(1), "event": .string("storage"), "key": .string("a\u{2028}b"),
            "value": .string("</script>"),
        ])
        let script = try #require(ArtifactBridge.hostScript(event))
        #expect(script.hasPrefix("typeof window.__nestHost===\"function\"&&window.__nestHost({"))
        #expect(script.hasSuffix("})"))
        #expect(script.contains(#""key":"a\u2028b""#))
        #expect(script.contains(#""value":"</script>""#))
        #expect(!script.contains("\u{2028}"))
        #expect(ArtifactBridge.hostScript(.number(1)) == nil)
        #expect(ArtifactBridge.hostScript(.object(["n": .number(.nan)])) == nil)
    }

    // MARK: The store

    func store() -> ArtifactsStore {
        api.set {
            $0.artifacts = [Fixture.artifact(kind: "html")]
            $0.artifactStorage = ["a1": ArtifactStorage(items: ["a": "1"], size: 2)]
        }
        return ArtifactsStore(api: api)
    }

    static func settle() async {
        await ArtifactBridgeTests.settle()
    }

    @Test func theStoreKnowsWhatEachPageStored() async throws {
        let store = store()
        #expect(store.storageSize(of: "a1") == 0)
        try await store.loadStorage("a1")
        #expect(store.storageSize(of: "a1") == 2)
        #expect(try await store.writeStorage("a1", .write(set: ["b": "22"], remove: ["a"])) == 3)
        #expect(api.calls.last == "writeArtifactStorage a1 set=b remove=a")
        #expect(store.storageSize(of: "a1") == 3)
        #expect(try await store.writeStorage("a1", .clear) == 0)
        #expect(api.calls.last == "clearArtifactStorage a1")
        #expect(store.storageSize(of: "a1") == 0)
        api.fail("writeArtifactStorage", with: APIError.payloadTooLarge("full"))
        await #expect(throws: APIError.payloadTooLarge("full")) {
            try await store.writeStorage("a1", .write(set: ["c": "3"], remove: []))
        }
    }

    @Test func storageEventsReachTheOpenPagesOfThatArtifact() async throws {
        let store = store()
        try await store.loadStorage("a1")
        var seen: [ArtifactStorageChange] = []
        let token = store.observeStorage("a1") { seen.append($0) }
        _ = store.observeStorage("a2") { _ in Issue.record("not this artifact") }
        api.set {
            $0.artifactStorage["a1"] = ArtifactStorage(items: ["a": "1", "b": "2"], size: 4)
        }
        let event = Fixture.event(
            EventType.artifactStorage, #"{"artifact_id": "a1", "set": {"b": "2"}, "remove": []}"#,
            session: nil)
        store.apply(event)
        #expect(seen == [.write(set: ["b": "2"], remove: [])])
        await Self.settle()
        // What it holds is read again, for the reader's line.
        #expect(store.storageSize(of: "a1") == 4)
        store.stopObserving(token)
        store.apply(event)
        #expect(seen.count == 1)
        // An artifact the reader never read storage for is not read on an event.
        store.apply(
            Fixture.event(
                EventType.artifactStorage, #"{"artifact_id": "a3", "clear": true}"#, session: nil))
        await Self.settle()
        #expect(!api.calls.contains("artifactStorage a3"))
    }

    @Test func aPageIsReadAgainWhenTheReaderComesBackToIt() async throws {
        let store = store()
        api.set {
            $0.artifacts = [
                Fixture.artifact(kind: "html", latest: 2, seen: true),
                Fixture.artifact(id: "a2", kind: "html", latest: 1, seen: true),
            ]
            $0.artifactContents = [
                "a1/1": Fixture.content("a1", 1, "old"), "a1/2": Fixture.content("a1", 2, "two"),
            ]
        }
        try await store.select("a1")
        try await store.select("a1", version: 1)
        // The page carries what it stored when it was read, so moving back reads it again.
        api.set { $0.artifactContents["a1/2"] = Fixture.content("a1", 2, "stored since") }
        try await store.select("a1")
        #expect(store.selectedContent?.content == "stored since")
        // Showing the same page again does not.
        try await store.select("a1")
        #expect(api.calls.filter { $0.hasPrefix("artifactContent") }.count == 3)
        // When the read fails, the page read before stays.
        try await store.select("a1", version: 1)
        api.fail("artifactContent")
        try await store.select("a1")
        #expect(store.selectedContent?.content == "stored since")
        await #expect(throws: APIError.server(status: 500, detail: "boom")) {
            try await store.select("a2")
        }
    }
}
