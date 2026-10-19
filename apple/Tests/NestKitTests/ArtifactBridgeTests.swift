import Foundation
import Testing

@testable import NestKit

/// B88: what an artifact page may ask Nest through `window.nest`, the checks before
/// anything runs, the "Open link?" prompt and in-page anchors.
@MainActor @Suite struct ArtifactBridgeTests {
    static func request(
        id: Any = "r1", method: Any = "openLink", params: Any = ["url": "https://example.com/a"],
        nest: Any = 1
    ) -> [String: Any] {
        ["nest": nest, "id": id, "method": method, "params": params]
    }

    static func failure(_ message: ArtifactBridge.Message) -> ArtifactBridge.Code? {
        if case .failed(_, let failure) = message {
            return failure.code
        }
        return nil
    }

    // MARK: Parsing

    @Test func aWellFormedOpenLinkBecomesACall() {
        #expect(
            ArtifactBridge.parse(Self.request())
                == .call(id: "r1", .openLink(URL(string: "https://example.com/a")!)))
        #expect(
            ArtifactBridge.parse(Self.request(params: ["url": "mailto:me@example.com"]))
                == .call(id: "r1", .openLink(URL(string: "mailto:me@example.com")!)))
        #expect(ArtifactBridge.parse(Self.request()).id == "r1")
    }

    @Test func aMessageWithoutAUsableIDIsIgnored() {
        #expect(ArtifactBridge.parse(nil) == .ignored)
        #expect(ArtifactBridge.parse("hello") == .ignored)
        #expect(ArtifactBridge.parse([1, 2]) == .ignored)
        #expect(ArtifactBridge.parse(["nest": 1, "method": "openLink"]) == .ignored)
        #expect(ArtifactBridge.parse(Self.request(id: 7)) == .ignored)
        #expect(
            ArtifactBridge.parse(Self.request(id: String(repeating: "x", count: 65))) == .ignored)
        #expect(ArtifactBridge.parse(Self.request()).id != nil)
        #expect(ArtifactBridge.Message.ignored.id == nil)
        #expect(ArtifactBridge.parse(Self.request(id: "")) == .ignored)
        #expect(ArtifactBridge.parse(Self.request(id: "", method: "x")) == .ignored)
        let longest = String(repeating: "x", count: 64)
        #expect(ArtifactBridge.parse(Self.request(id: longest)).id == longest)
    }

    @Test func aMalformedRequestWithAnIDIsABadRequest() {
        for body in [
            Self.request(nest: 2), Self.request(nest: "1"), Self.request(nest: true),
            Self.request(nest: 1.5), Self.request(method: 3), Self.request(params: "x"),
            Self.request(params: [1]), Self.request(params: NSNull()),
            ["nest": 1, "id": "r1", "method": "openLink"],
            Self.request(params: ["url": Date()]),
        ] {
            #expect(Self.failure(ArtifactBridge.parse(body)) == .badRequest)
        }
        #expect(ArtifactBridge.parse(Self.request(nest: 2)).id == "r1")
    }

    @Test func aRequestOverSixtyFourKibibytesIsTooLarge() {
        let filler = String(repeating: "a", count: 64 * 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request(params: ["url": filler]))) == .tooLarge)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request(method: "later", params: ["x": filler])))
                == .tooLarge)
        let fits = String(repeating: "a", count: 60 * 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request(method: "later", params: ["x": fits])))
                == .unknownMethod)
    }

    @Test func onlyAllowedMethodsRun() {
        for method in ["fetch", "openlink", "", "storage.get"] {
            #expect(
                Self.failure(ArtifactBridge.parse(Self.request(method: method))) == .unknownMethod)
        }
        #expect(
            ArtifactBridge.methods == [
                "openLink", "saveDocument", "storageWrite", "storageClear", "saveFile", "usage",
                "ask",
            ])
    }

    static func save(_ params: Any = ["content": "# Plan\n", "base_version": 3])
        -> [String: Any]
    {
        request(method: "saveDocument", params: params)
    }

    @Test func saveDocumentTakesTextAndAWholeBaseVersion() {
        #expect(
            ArtifactBridge.parse(Self.save())
                == .call(id: "r1", .saveDocument(content: "# Plan\n", baseVersion: 3)))
        #expect(
            ArtifactBridge.parse(Self.save(["content": "", "base_version": 1.0]))
                == .call(id: "r1", .saveDocument(content: "", baseVersion: 1)))
        for params: [String: Any] in [
            [:], ["content": "x"], ["base_version": 2], ["content": 5, "base_version": 2],
            ["content": "x", "base_version": "2"], ["content": "x", "base_version": true],
            ["content": "x", "base_version": 2.5], ["content": "x", "base_version": 0],
            ["content": "x", "base_version": -1], ["content": "x", "base_version": 1e300],
            ["content": "x", "base_version": NSNull()],
        ] {
            #expect(
                Self.failure(ArtifactBridge.parse(Self.save(params))) == .badRequest, "\(params)")
        }
    }

    @Test func saveDocumentMayCarryAWholeArtifactButNoMore() {
        let mebibyte = String(repeating: "a", count: 1024 * 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.save(["content": mebibyte, "base_version": 2])))
                == nil)
        let over = String(repeating: "a", count: 1024 * 1024 + 1024)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.save(["content": over, "base_version": 2])))
                == .tooLarge)
        // The larger limit is saveDocument's alone.
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request(params: ["url": mebibyte])))
                == .tooLarge)
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request(method: 7, params: ["x": mebibyte])))
                == .tooLarge)
    }

    @Test func openLinkTakesOnlyAbsoluteWebAndMailLinks() {
        for url: Any in [
            "javascript:alert(1)", "data:text/html,<p>x</p>", "/relative", "page.html", "#top",
            "file:///etc/passwd", "https:no-host", "http://", "", 42, "ftp://example.com",
            "https://example.com/" + String(repeating: "a", count: 2048),
        ] {
            #expect(
                Self.failure(ArtifactBridge.parse(Self.request(params: ["url": url])))
                    == .badRequest,
                "\(url)")
        }
        #expect(
            Self.failure(ArtifactBridge.parse(Self.request(params: [:]))) == .badRequest)
        let longest = "https://e.com/" + String(repeating: "a", count: 2048 - 14)
        #expect(ArtifactBridge.parse(Self.request(params: ["url": longest])).id == "r1")
        #expect(Self.failure(ArtifactBridge.parse(Self.request(params: ["url": longest]))) == nil)
        #expect(
            ArtifactBridge.link("HTTPS://Example.COM")?.absoluteString == "https://example.com/")
        #expect(ArtifactBridge.link("http://example.com")?.absoluteString == "http://example.com/")
        #expect(
            ArtifactBridge.link("https://example.com?q=1#top")?.absoluteString
                == "https://example.com/?q=1#top")
        #expect(
            ArtifactBridge.link("https://Example.com/A/b")?.absoluteString
                == "https://example.com/A/b")
        #expect(
            ArtifactBridge.link("MAILTO:me@example.com")?.absoluteString == "mailto:me@example.com")
        #expect(
            ArtifactBridge.parse(Self.request(params: ["url": "https://example.com"]))
                == .call(id: "r1", .openLink(URL(string: "https://example.com/")!)))
    }

    // MARK: Replies

    @Test func repliesCarryTheIDAndAResultOrAnError() {
        let ok = ArtifactBridge.Reply("r1", .success(.object(["opened": .bool(true)]))).body
        #expect(ok["nest"] as? Int == 1)
        #expect(ok["id"] as? String == "r1")
        #expect(ok["ok"] as? Bool == true)
        #expect((ok["result"] as? [String: Any])?["opened"] as? Bool == true)
        let failed = ArtifactBridge.Reply(
            "r2", .failure(ArtifactBridge.Failure(.declined, "The link was not opened."))
        ).body
        #expect(failed["nest"] as? Int == 1)
        #expect(failed["id"] as? String == "r2")
        #expect(failed["ok"] as? Bool == false)
        let error = failed["error"] as? [String: Any]
        #expect(error?["code"] as? String == "declined")
        #expect(error?["message"] as? String == "The link was not opened.")
        #expect(
            ArtifactBridge.Code.allCases.map(\.rawValue) == [
                "unknown_method", "bad_request", "too_large", "rate_limited", "busy", "declined",
                "unavailable", "conflict", "quota", "budget", "disabled",
            ])
    }

    @Test func valuesBecomeWhatWebKitSends() throws {
        let value = ArtifactBridge.Value.object([
            "none": .null, "yes": .bool(true), "n": .number(2.5), "s": .string("x"),
            "list": .array([.number(1), .string("y")]),
        ])
        let object = try #require(value.foundation as? [String: Any])
        #expect(object["none"] is NSNull)
        #expect(object["yes"] as? Bool == true)
        #expect(object["n"] as? Double == 2.5)
        #expect(object["s"] as? String == "x")
        let list = try #require(object["list"] as? [Any])
        #expect(list[0] as? Double == 1)
        #expect(list[1] as? String == "y")
        #expect(JSONSerialization.isValidJSONObject(object))
    }

    // MARK: Rate

    @Test func thirtyRequestsPassInTenSecondsThenTheWindowSlides() {
        var gate = ArtifactRateGate()
        let start = Date(timeIntervalSince1970: 1_000)
        func admit(_ seconds: Double) -> Bool {
            gate.admit(at: start.addingTimeInterval(seconds))
        }
        for index in 0..<30 {
            #expect(admit(Double(index) * 0.1))
        }
        #expect(!admit(5))
        #expect(!admit(9.99))
        #expect(admit(10))
        #expect(!admit(10.05))
        #expect(admit(10.1))
        #expect(admit(30))
    }

    // MARK: Anchors and the prompt's text

    @Test func onlyAFragmentOfTheSameDocumentIsAnAnchor() {
        let blank = URL(string: "about:blank")
        #expect(ArtifactBridge.isAnchor(URL(string: "about:blank#section"), in: blank))
        #expect(
            ArtifactBridge.isAnchor(URL(string: "about:blank#b"), in: URL(string: "about:blank#a")))
        #expect(!ArtifactBridge.isAnchor(URL(string: "about:blank"), in: blank))
        #expect(!ArtifactBridge.isAnchor(URL(string: "https://example.com/#x"), in: blank))
        #expect(!ArtifactBridge.isAnchor(nil, in: blank))
        #expect(!ArtifactBridge.isAnchor(URL(string: "about:blank#x"), in: nil))
    }

    @Test func theMessageIsTheURLWithTheHostFirstWhenItIsLong() {
        let short = URL(string: "https://example.com/a")!
        #expect(ArtifactBridge.linkMessage(short) == "https://example.com/a")
        let long = URL(string: "https://docs.example.com/" + String(repeating: "p", count: 80))!
        #expect(ArtifactBridge.linkMessage(long) == "docs.example.com\n\(long.absoluteString)")
        let mail = URL(string: "mailto:" + String(repeating: "m", count: 80) + "@example.com")!
        #expect(ArtifactBridge.linkMessage(mail) == mail.absoluteString)
        let hosted = URL(string: "mailto://example.com/" + String(repeating: "m", count: 80))!
        #expect(ArtifactBridge.linkMessage(hosted) == hosted.absoluteString)
        let sixty = URL(string: "https://example.com/" + String(repeating: "p", count: 40))!
        #expect(sixty.absoluteString.count == 60)
        #expect(ArtifactBridge.linkMessage(sixty) == sixty.absoluteString)
    }

    // MARK: The prompt

    static func choose(_ prompt: ArtifactLinkPrompt, _ open: Bool) {
        guard let request = prompt.request else {
            Issue.record("Nothing is being asked")
            return
        }
        prompt.answer(open, to: request.id)
    }

    static func settle() async {
        for _ in 0..<20 {
            await Task.yield()
        }
    }

    @Test func thePromptAnswersOnceAndASecondAskIsBusy() async throws {
        let prompt = ArtifactLinkPrompt()
        let url = URL(string: "https://example.com")!
        #expect(prompt.request == nil)
        let first = Task { await prompt.ask(url) }
        await Self.settle()
        let request = try #require(prompt.request)
        #expect(request.url == url)
        #expect(request.message == "https://example.com")
        #expect(await prompt.ask(url) == .busy)
        prompt.answer(false, to: UUID())
        #expect(prompt.request != nil)
        prompt.answer(true, to: request.id)
        #expect(prompt.request == nil)
        #expect(await first.value == .open)
        prompt.answer(true, to: request.id)

        let second = Task { await prompt.ask(url) }
        await Self.settle()
        Self.choose(prompt, false)
        #expect(await second.value == .declined)
    }

    @Test func dismissingThePromptEndsTheWait() async {
        let prompt = ArtifactLinkPrompt()
        prompt.dismiss()
        let asked = Task { await prompt.ask(URL(string: "https://example.com")!) }
        await Self.settle()
        prompt.dismiss()
        #expect(prompt.request == nil)
        #expect(await asked.value == .dismissed)
    }

    // MARK: The session

    final class Opened {
        var urls: [URL] = []
    }

    static func saving(_ save: ArtifactBridgeSession.Save?) -> ArtifactBridgeSession {
        ArtifactBridgeSession(prompt: ArtifactLinkPrompt(), save: save) { _ in }
    }

    static func session(
        _ prompt: ArtifactLinkPrompt, opened: Opened, clock: (() -> Date)? = nil
    ) -> ArtifactBridgeSession {
        guard let clock else {
            return ArtifactBridgeSession(prompt: prompt) { opened.urls.append($0) }
        }
        return ArtifactBridgeSession(prompt: prompt, now: clock) { opened.urls.append($0) }
    }

    static func code(_ reply: ArtifactBridge.Reply?) -> ArtifactBridge.Code? {
        if case .failure(let failure) = reply?.outcome {
            return failure.code
        }
        return nil
    }

    @Test func openLinkAsksThenOpensAndReplies() async {
        let prompt = ArtifactLinkPrompt()
        let opened = Opened()
        let session = Self.session(prompt, opened: opened)
        let reply = Task { await session.receive(Self.request()) }
        await Self.settle()
        #expect(opened.urls.isEmpty)
        Self.choose(prompt, true)
        #expect(
            await reply.value
                == ArtifactBridge.Reply("r1", .success(.object(["opened": .bool(true)]))))
        #expect(opened.urls == [URL(string: "https://example.com/a")!])
    }

    @Test func cancelDeclinesAndASecondCallWhileAskingIsBusy() async {
        let prompt = ArtifactLinkPrompt()
        let opened = Opened()
        let session = Self.session(prompt, opened: opened)
        let first = Task { await session.receive(Self.request()) }
        await Self.settle()
        #expect(Self.code(await session.receive(Self.request(id: "r2"))) == .busy)
        Self.choose(prompt, false)
        #expect(Self.code(await first.value) == .declined)
        let dismissed = Task { await session.receive(Self.request(id: "r3")) }
        await Self.settle()
        prompt.dismiss()
        #expect(Self.code(await dismissed.value) == .declined)
        #expect(opened.urls.isEmpty)
    }

    @Test func badMessagesGetTheirErrorsAndUnusableOnesNone() async {
        let session = Self.session(ArtifactLinkPrompt(), opened: Opened())
        #expect(await session.receive("nothing") == nil)
        #expect(Self.code(await session.receive(Self.request(method: "fetch"))) == .unknownMethod)
        #expect(
            Self.code(await session.receive(Self.request(params: ["url": "javascript:alert(1)"])))
                == .badRequest)
    }

    @Test func aBurstOverThirtyIsRateLimitedUntilTheWindowPasses() async {
        var now = Date(timeIntervalSince1970: 0)
        let session = Self.session(ArtifactLinkPrompt(), opened: Opened()) { now }
        for _ in 0..<40 {
            #expect(await session.receive(Self.request(id: "")) == nil)
        }
        for _ in 0..<30 {
            #expect(Self.code(await session.receive(Self.request(method: "x"))) == .unknownMethod)
        }
        #expect(Self.code(await session.receive(Self.request())) == .rateLimited)
        #expect(await session.receive(42) == nil)
        now = now.addingTimeInterval(9)
        for _ in 0..<50 {
            #expect(Self.code(await session.receive(Self.request(method: "x"))) == .rateLimited)
        }
        now = now.addingTimeInterval(1)
        for _ in 0..<30 {
            #expect(Self.code(await session.receive(Self.request(method: "x"))) == .unknownMethod)
        }
        #expect(Self.code(await session.receive(Self.request(method: "x"))) == .rateLimited)
    }

    @Test func aFollowedLinkAsksThenOpensWithoutAReply() async {
        let prompt = ArtifactLinkPrompt()
        let opened = Opened()
        let session = Self.session(prompt, opened: opened)
        let url = URL(string: "https://example.com/b")!
        let followed = Task { await session.follow(url) }
        await Self.settle()
        Self.choose(prompt, true)
        await followed.value
        #expect(opened.urls == [url])

        let cancelled = Task { await session.follow(url) }
        await Self.settle()
        Self.choose(prompt, false)
        await cancelled.value
        #expect(opened.urls == [url])

        await session.follow(URL(string: "file:///etc/passwd")!)
        #expect(prompt.request == nil)
    }

    @Test func followedLinksCountTowardTheRate() async {
        let prompt = ArtifactLinkPrompt()
        let session = Self.session(prompt, opened: Opened()) { Date(timeIntervalSince1970: 0) }
        for _ in 0..<30 {
            _ = await session.receive(Self.request(method: "x"))
        }
        await session.follow(URL(string: "https://example.com")!)
        #expect(prompt.request == nil)
    }

    // MARK: Saving a document

    final class Saves {
        var made: [(String, Int)] = []
    }

    @Test func saveDocumentSavesAndRepliesWithTheNewVersion() async {
        let saves = Saves()
        let session = Self.saving { content, base in
            saves.made.append((content, base))
            return base + 1
        }
        #expect(
            await session.receive(Self.save())
                == ArtifactBridge.Reply("r1", .success(.object(["version": .number(4)]))))
        #expect(saves.made.map(\.0) == ["# Plan\n"])
        #expect(saves.made.map(\.1) == [3])
    }

    @Test func aPageThatCannotSaveIsABadRequest() async {
        let none = Self.saving(nil)
        #expect(Self.code(await none.receive(Self.save())) == .badRequest)
        let refused = Self.saving { _, _ in
            throw ArtifactsStore.SaveRefused()
        }
        #expect(Self.code(await refused.receive(Self.save())) == .badRequest)
    }

    @Test func aStaleBaseIsAConflictAndOtherFailuresUnavailable() async {
        let stale = Self.saving { _, _ in
            throw APIError.conflict("The document changed.")
        }
        #expect(Self.code(await stale.receive(Self.save())) == .conflict)
        let down = Self.saving { _, _ in
            throw APIError.transport("offline")
        }
        #expect(Self.code(await down.receive(Self.save())) == .unavailable)
        let cancelled = Self.saving { _, _ in throw CancellationError() }
        #expect(Self.code(await cancelled.receive(Self.save())) == .unavailable)
        let invalid = Self.saving { _, _ in
            throw APIError.invalidInput("Empty")
        }
        let reply = await invalid.receive(Self.save())
        #expect(Self.code(reply) == .unavailable)
        if case .failure(let failure) = reply?.outcome {
            #expect(failure.message == "Nest could not save the document: Empty")
        }
    }
}
