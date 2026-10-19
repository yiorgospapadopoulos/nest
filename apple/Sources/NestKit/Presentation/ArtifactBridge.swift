import CoreFoundation
import Foundation
import Observation

/// What an artifact page may ask Nest through `window.nest` (B88, D115), checked before
/// anything runs: the request's shape and size, then the method allow-list and its params.
/// A later method is one entry in `decoders` plus its case in `ArtifactBridgeSession.run`.
public enum ArtifactBridge {
    /// The web view's script message handler name.
    public static let handlerName = "nest"
    static let longestID = 64
    static let largestRequest = 64 * 1024
    /// Methods allowed more than `largestRequest`: a saved document is at most the 1 MiB
    /// an artifact holds, and the request around it.
    static let largestRequests = [
        "saveDocument": 1024 * 1024 + 1024, "storageWrite": 2 * 1024 * 1024 + 4 * 1024,
        "saveFile": 24 * 1024 * 1024, "ask": 16 * 1024,
    ]
    static let longestPrompt = 8_000
    static let longestSystem = 4_000
    static let longestKey = 256
    static let largestValue = 256 * 1024
    static let longestURL = 2048
    /// Above this length the prompt names the host before the full URL.
    static let longURL = 60

    public enum Code: String, CaseIterable, Sendable {
        case unknownMethod = "unknown_method"
        case badRequest = "bad_request"
        case tooLarge = "too_large"
        case rateLimited = "rate_limited"
        case busy
        case declined
        case unavailable
        /// The document changed since the page was opened (B88).
        case conflict
        /// Storage over a cap; the message names it.
        case quota
        /// Today's asks for the artifact are used; the message says when more come.
        case budget
        /// Asking Claude is turned off in Nest's settings.
        case disabled
    }

    public struct Failure: Error, Equatable, Sendable {
        public let code: Code
        public let message: String

        public init(_ code: Code, _ message: String) {
            self.code = code
            self.message = message
        }
    }

    /// A checked request the host can run.
    public enum Call: Equatable, Sendable {
        case openLink(URL)
        case saveDocument(content: String, baseVersion: Int)
        case storage(ArtifactStorageChange)
        case saveFile(name: String, data: Data)
        case usage
        case ask(prompt: String, system: String?)
    }

    public enum Message: Equatable, Sendable {
        /// No usable id, so no reply.
        case ignored
        case failed(id: String, Failure)
        case call(id: String, Call)

        public var id: String? { request?.id }

        /// The id to answer and what the request asks for or why it is refused.
        public var request: (id: String, outcome: Result<Call, Failure>)? {
            switch self {
            case .ignored: nil
            case .failed(let id, let failure): (id, .failure(failure))
            case .call(let id, let call): (id, .success(call))
            }
        }
    }

    /// Each allowed method and how its params become a call.
    static let decoders: [String: @Sendable ([String: Any]) -> Result<Call, Failure>] = [
        "openLink": openLink, "saveDocument": saveDocument, "storageWrite": storageWrite,
        "storageClear": { _ in .success(.storage(.clear)) }, "saveFile": saveFile,
        "usage": { _ in .success(.usage) }, "ask": ask,
    ]

    static var methods: Set<String> { Set(decoders.keys) }

    /// The page's message body as WebKit hands it over.
    public static func parse(_ body: Any?) -> Message {
        guard let request = body as? [String: Any], let id = request["id"] as? String,
            (1...longestID).contains(id.utf16.count)
        else { return .ignored }
        guard JSONSerialization.isValidJSONObject(request),
            let data = try? JSONSerialization.data(
                withJSONObject: request, options: .withoutEscapingSlashes)
        else { return .failed(id: id, Failure(.badRequest, "The request is not plain JSON.")) }
        let limit = (request["method"] as? String).flatMap { largestRequests[$0] } ?? largestRequest
        guard data.count <= limit else {
            return .failed(id: id, Failure(.tooLarge, "The request is over \(limit / 1024) KiB."))
        }
        guard isOne(request["nest"]), let method = request["method"] as? String,
            let params = request["params"] as? [String: Any]
        else { return .failed(id: id, Failure(.badRequest, "The request is malformed.")) }
        guard let decode = decoders[method] else {
            return .failed(id: id, Failure(.unknownMethod, "Nest has no method \(method)."))
        }
        switch decode(params) {
        case .success(let call): return .call(id: id, call)
        case .failure(let failure): return .failed(id: id, failure)
        }
    }

    /// The number 1, not `true`, which WebKit also hands over as an NSNumber.
    private static func isOne(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber,
            CFGetTypeID(number) != CFBooleanGetTypeID()
        else { return false }
        return number == 1
    }

    private static func openLink(_ params: [String: Any]) -> Result<Call, Failure> {
        guard let text = params["url"] as? String, let url = link(text) else {
            return .failure(Failure(.badRequest, "Only http, https and mailto links open."))
        }
        return .success(.openLink(url))
    }

    /// The document's whole Markdown and the version it was edited from, a whole number
    /// from 1.
    private static func saveDocument(_ params: [String: Any]) -> Result<Call, Failure> {
        guard let content = params["content"] as? String,
            let number = params["base_version"] as? NSNumber,
            CFGetTypeID(number) != CFBooleanGetTypeID(),
            let base = Int(exactly: number.doubleValue), base >= 1
        else {
            return .failure(
                Failure(
                    .badRequest,
                    "saveDocument needs the content as text and the base_version it was edited from."
                ))
        }
        return .success(.saveDocument(content: content, baseVersion: base))
    }

    /// Keys of 1 to 256 characters set to strings of at most 256 KiB, and keys removed;
    /// either may be left out. The daemon checks the totals.
    private static func storageWrite(_ params: [String: Any]) -> Result<Call, Failure> {
        let badRequest = Failure(
            .badRequest,
            "storageWrite needs set, keys of 1 to 256 characters to text, and remove, a list of keys."
        )
        guard let set = (params["set"] ?? [String: String]()) as? [String: String],
            let remove = (params["remove"] ?? [String]()) as? [String],
            (set.keys + remove).allSatisfy({ (1...longestKey).contains($0.count) })
        else { return .failure(badRequest) }
        guard set.values.allSatisfy({ $0.utf8.count <= largestValue }) else {
            return .failure(Failure(.quota, "A stored value is over 256 KiB."))
        }
        return .success(.storage(.write(set: set, remove: remove)))
    }

    /// A prompt of 1 to 8,000 characters and an optional system text of up to 4,000.
    private static func ask(_ params: [String: Any]) -> Result<Call, Failure> {
        guard let prompt = params["prompt"] as? String,
            (1...longestPrompt).contains(prompt.count),
            params["system"] == nil
                || (params["system"] as? String).map({
                    $0.count <= longestSystem
                }) == true
        else {
            return .failure(
                Failure(
                    .badRequest,
                    "ask needs a prompt of 1 to 8,000 characters and a system text of at most 4,000."
                ))
        }
        return .success(.ask(prompt: prompt, system: params["system"] as? String))
    }

    /// A file name, cleaned for the disk, and its content as text or base64.
    private static func saveFile(_ params: [String: Any]) -> Result<Call, Failure> {
        let encoding = params["encoding"] ?? "utf8"
        guard let raw = params["name"] as? String, let content = params["content"] as? String,
            params["mime"] == nil || params["mime"] is String
        else {
            return .failure(Failure(.badRequest, "saveFile needs a name and the content as text."))
        }
        let name = ArtifactFile.clean(raw)
        guard !name.isEmpty else {
            return .failure(Failure(.badRequest, "saveFile needs a usable file name."))
        }
        let data: Data? =
            switch encoding as? String {
            case "utf8": Data(content.utf8)
            case "base64": Data(base64Encoded: content)
            default: nil
            }
        guard let data else {
            return .failure(
                Failure(.badRequest, "saveFile takes utf8 or valid base64 content."))
        }
        return .success(.saveFile(name: name, data: data))
    }

    /// The script that hands one host event, an object, to the page's shim; nil when it is
    /// not a JSON object. Line and paragraph separators are escaped for the script's sake.
    public static func hostScript(_ event: Value) -> String? {
        let object = event.foundation
        // Serializing a NaN raises rather than throws, so the event is checked first.
        guard JSONSerialization.isValidJSONObject(object),
            let data = try? JSONSerialization.data(
                withJSONObject: object,
                options: [.sortedKeys, .withoutEscapingSlashes])
        else { return nil }
        let json = String(decoding: data, as: UTF8.self)
            .replacingOccurrences(of: "\u{2028}", with: "\\u2028")
            .replacingOccurrences(of: "\u{2029}", with: "\\u2029")
        return "typeof window.__nestHost===\"function\"&&window.__nestHost(\(json))"
    }

    /// The text as a link a page may open: absolute, at most 2,048 characters, a web
    /// page with a host or a mail address (`SafeLink`), in the form a browser would show
    /// it (scheme and host in lower case, `/` for an empty web path), which the prompt
    /// shows and the browser opens.
    static func link(_ text: String) -> URL? {
        guard text.utf16.count <= longestURL, let url = SafeLink.url(text),
            var parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
        else { return nil }
        parts.scheme = parts.scheme?.lowercased()
        if parts.scheme != "mailto" {
            guard let host = parts.host, !host.isEmpty else { return nil }
            parts.host = host.lowercased()
            if parts.path.isEmpty {
                parts.path = "/"
            }
        }
        return parts.url
    }

    /// A JSON value the host sends back to the page.
    public indirect enum Value: Equatable, Sendable {
        case null
        case bool(Bool)
        case number(Double)
        case string(String)
        case array([Value])
        case object([String: Value])

        /// As WebKit takes it for the page.
        public var foundation: Any {
            switch self {
            case .null: NSNull()
            case .bool(let value): value
            case .number(let value): value
            case .string(let value): value
            case .array(let values): values.map(\.foundation)
            case .object(let values): values.mapValues(\.foundation)
            }
        }
    }

    /// The answer to one request.
    public struct Reply: Equatable, Sendable {
        public let id: String
        public let outcome: Result<Value, Failure>

        public init(_ id: String, _ outcome: Result<Value, Failure>) {
            self.id = id
            self.outcome = outcome
        }

        /// `{nest: 1, id, ok: true, result}` or `{nest: 1, id, ok: false, error: {code, message}}`.
        public var body: [String: Any] {
            switch outcome {
            case .success(let result):
                ["nest": 1, "id": id, "ok": true, "result": result.foundation]
            case .failure(let failure):
                [
                    "nest": 1, "id": id, "ok": false,
                    "error": ["code": failure.code.rawValue, "message": failure.message],
                ]
            }
        }
    }

    /// A link click that only moves to a fragment of the page's own document, which the
    /// web view may follow.
    public static func isAnchor(_ target: URL?, in document: URL?) -> Bool {
        guard let target, let document, target.fragment != nil else { return false }
        return withoutFragment(target) == withoutFragment(document)
    }

    private static func withoutFragment(_ url: URL) -> Substring {
        url.absoluteString.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false)[0]
    }

    /// The prompt's message: the full URL, after its host when it is long.
    public static func linkMessage(_ url: URL) -> String {
        let full = url.absoluteString
        guard full.count > longURL, url.scheme != "mailto", let host = url.host(), !host.isEmpty
        else { return full }
        return "\(host)\n\(full)"
    }
}

/// At most 30 requests in any 10 seconds from one open page.
public struct ArtifactRateGate: Sendable {
    static let limit = 30
    static let window: TimeInterval = 10
    private var admitted: [Date] = []

    public init() {}

    public mutating func admit(at now: Date) -> Bool {
        admitted.removeAll { now.timeIntervalSince($0) >= Self.window }
        guard admitted.count < Self.limit else { return false }
        admitted.append(now)
        return true
    }
}

/// The reader's "Open link?" question, one at a time.
@MainActor @Observable
public final class ArtifactLinkPrompt {
    public struct Request: Identifiable, Equatable, Sendable {
        public let id: UUID
        public let url: URL

        public var message: String { ArtifactBridge.linkMessage(url) }
    }

    public enum Answer: Equatable, Sendable {
        case open, declined, busy
        /// The reader closed or moved on while it asked.
        case dismissed
    }

    public private(set) var request: Request?
    @ObservationIgnored private var waiting: CheckedContinuation<Answer, Never>?

    public init() {}

    public func ask(_ url: URL) async -> Answer {
        guard request == nil else { return .busy }
        return await withCheckedContinuation { continuation in
            waiting = continuation
            request = Request(id: UUID(), url: url)
        }
    }

    /// The user's choice for the request with this id; a stale id does nothing.
    public func answer(_ open: Bool, to id: UUID) {
        guard request?.id == id else { return }
        finish(open ? .open : .declined)
    }

    public func dismiss() {
        finish(.dismissed)
    }

    private func finish(_ answer: Answer) {
        request = nil
        waiting?.resume(returning: answer)
        waiting = nil
    }
}

/// One open page's side of the bridge: its rate window, the checks and the calls.
@MainActor
public final class ArtifactBridgeSession {
    /// Saves the page's document from a base version and answers the new version; nil
    /// for a page that is not a document.
    public typealias Save = @MainActor (_ content: String, _ baseVersion: Int) async throws -> Int
    /// Writes the page's storage change and answers the storage's new size.
    public typealias Storage = @MainActor (ArtifactStorageChange) async throws -> Int
    /// Asks where to save the file and writes it; false when the user cancels.
    public typealias SaveFile = @MainActor (_ name: String, _ data: Data) async -> Bool
    /// The usage snapshot `nest.usage()` answers.
    public typealias Usage = @MainActor () async throws -> ArtifactBridge.Value
    /// Asks Claude for the page.
    public typealias Ask =
        @MainActor (_ prompt: String, _ system: String?) async throws ->
        ArtifactAnswer
    /// Own writes remembered so their echo from the daemon is not handed back.
    static let rememberedWrites = 50

    private let prompt: ArtifactLinkPrompt
    private let now: () -> Date
    private let save: Save?
    private let storage: Storage?
    private let saveFile: SaveFile?
    private let usage: Usage?
    private let ask: Ask?
    /// The page read its usage, so it hears when usage changes.
    private var wantsUsage = false
    /// This page's storage changes the daemon has not echoed yet, oldest first.
    private var ownWrites: [ArtifactStorageChange] = []
    private let open: (URL) -> Void
    private var gate = ArtifactRateGate()

    public init(
        prompt: ArtifactLinkPrompt, now: @escaping () -> Date = { Date() }, save: Save? = nil,
        storage: Storage? = nil, saveFile: SaveFile? = nil, usage: Usage? = nil, ask: Ask? = nil,
        open: @escaping (URL) -> Void
    ) {
        self.prompt = prompt
        self.now = now
        self.save = save
        self.storage = storage
        self.saveFile = saveFile
        self.usage = usage
        self.ask = ask
        self.open = open
    }

    /// The reply to a message the page posted, nil when it is ignored.
    public func receive(_ body: Any?) async -> ArtifactBridge.Reply? {
        guard let (id, outcome) = ArtifactBridge.parse(body).request else { return nil }
        guard gate.admit(at: now()) else {
            return ArtifactBridge.Reply(
                id,
                .failure(ArtifactBridge.Failure(.rateLimited, "Too many requests; wait a moment.")))
        }
        switch outcome {
        case .success(let call): return ArtifactBridge.Reply(id, await run(call))
        case .failure(let failure): return ArtifactBridge.Reply(id, .failure(failure))
        }
    }

    private func run(_ call: ArtifactBridge.Call) async -> Result<
        ArtifactBridge.Value, ArtifactBridge.Failure
    > {
        switch call {
        case .openLink(let url):
            switch await prompt.ask(url) {
            case .open:
                open(url)
                return .success(.object(["opened": .bool(true)]))
            case .busy:
                return .failure(
                    ArtifactBridge.Failure(.busy, "Nest is already asking about a link."))
            case .declined, .dismissed:
                return .failure(ArtifactBridge.Failure(.declined, "The link was not opened."))
            }
        case .saveDocument(let content, let baseVersion):
            return await saveDocument(content, baseVersion: baseVersion)
        case .storage(let change):
            return await write(change)
        case .saveFile(let name, let data):
            guard let saveFile else { return .failure(Self.unavailable) }
            guard await saveFile(name, data) else {
                return .failure(ArtifactBridge.Failure(.declined, "The file was not saved."))
            }
            return .success(.object(["saved": .bool(true)]))
        case .usage:
            wantsUsage = true
            guard let usage else { return .failure(Self.unavailable) }
            do {
                return .success(try await usage())
            } catch {
                return .failure(
                    ArtifactBridge.Failure(
                        .unavailable, "Nest could not read the usage: \(Self.describe(error))"))
            }
        case .ask(let prompt, let system):
            guard let ask else { return .failure(Self.unavailable) }
            do {
                let answer = try await ask(prompt, system)
                return .success(
                    .object([
                        "text": .string(answer.text),
                        "remaining": .number(Double(answer.remaining)),
                    ]))
            } catch {
                return .failure(Self.askFailure(error))
            }
        }
    }

    private func saveDocument(_ content: String, baseVersion: Int) async -> Result<
        ArtifactBridge.Value, ArtifactBridge.Failure
    > {
        let refused = ArtifactBridge.Failure(
            .badRequest, "Only the latest version of a document can be saved.")
        guard let save else { return .failure(refused) }
        do {
            let version = try await save(content, baseVersion)
            return .success(.object(["version": .number(Double(version))]))
        } catch is ArtifactsStore.SaveRefused {
            return .failure(refused)
        } catch APIError.conflict {
            return .failure(
                ArtifactBridge.Failure(.conflict, "This document changed since it was opened."))
        } catch {
            return .failure(
                ArtifactBridge.Failure(
                    .unavailable, "Nest could not save the document: \(Self.describe(error))"))
        }
    }

    private static let unavailable = ArtifactBridge.Failure(
        .unavailable, "This page cannot do that in Nest.")

    private func write(_ change: ArtifactStorageChange) async -> Result<
        ArtifactBridge.Value, ArtifactBridge.Failure
    > {
        guard let storage else { return .failure(Self.unavailable) }
        ownWrites = Array((ownWrites + [change]).suffix(Self.rememberedWrites))
        do {
            let size = try await storage(change)
            return .success(.object(["size": .number(Double(size))]))
        } catch {
            if let index = ownWrites.lastIndex(of: change) {
                ownWrites.remove(at: index)
            }
            return .failure(Self.storageFailure(error))
        }
    }

    /// The day's limit is `budget`, asking turned off `disabled`, an ask already running
    /// `busy`; anything else `unavailable`.
    private static func askFailure(_ error: any Error) -> ArtifactBridge.Failure {
        if let used = error as? ArtifactsStore.AskBudgetUsed {
            return ArtifactBridge.Failure(.budget, used.message)
        }
        return switch error as? APIError {
        case .rateLimited(let detail, _): ArtifactBridge.Failure(.budget, detail)
        case .server(403, let detail): ArtifactBridge.Failure(.disabled, detail)
        case .conflict(let detail): ArtifactBridge.Failure(.busy, detail)
        default:
            ArtifactBridge.Failure(.unavailable, "Claude could not answer: \(describe(error))")
        }
    }

    /// The host event for a fresh usage snapshot, only for a page that read its usage.
    public func usageEvents(for snapshot: ArtifactBridge.Value) -> [ArtifactBridge.Value] {
        guard wantsUsage else { return [] }
        return [.object(["nest": .number(1), "event": .string("usage"), "usage": snapshot])]
    }

    /// Over a cap is `quota`, a key the daemon refused `bad_request`.
    private static func storageFailure(_ error: any Error) -> ArtifactBridge.Failure {
        switch error as? APIError {
        case .payloadTooLarge(let detail): ArtifactBridge.Failure(.quota, detail)
        case .invalidInput(let detail): ArtifactBridge.Failure(.badRequest, detail)
        default:
            ArtifactBridge.Failure(.unavailable, "Nest could not store that: \(describe(error))")
        }
    }

    /// The host events for a storage change the daemon reported: one per key set or
    /// removed, or one for a clear; none for this page's own write coming back.
    public func hostEvents(for change: ArtifactStorageChange) -> [ArtifactBridge.Value] {
        if let index = ownWrites.firstIndex(of: change) {
            ownWrites.remove(at: index)
            return []
        }
        func event(_ fields: [String: ArtifactBridge.Value]) -> ArtifactBridge.Value {
            var event = fields
            event["nest"] = .number(1)
            event["event"] = .string("storage")
            return .object(event)
        }
        switch change {
        case .clear:
            return [event(["clear": .bool(true)])]
        case .write(let set, let remove):
            return set.sorted { $0.key < $1.key }.map {
                event(["key": .string($0.key), "value": .string($0.value)])
            } + remove.map { event(["key": .string($0), "value": .null]) }
        }
    }

    private static func describe(_ error: any Error) -> String {
        (error as? APIError)?.message ?? error.localizedDescription
    }

    /// A link click the page did not route through `window.nest`: the same question, then
    /// the browser, with no reply.
    public func follow(_ url: URL) async {
        guard let url = ArtifactBridge.link(url.absoluteString), gate.admit(at: now()),
            await prompt.ask(url) == .open
        else { return }
        open(url)
    }
}
