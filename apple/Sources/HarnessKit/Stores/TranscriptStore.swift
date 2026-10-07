import Foundation
import Observation

/// A tool call of the main agent, with its result once it arrives.
public struct ToolCall: Sendable, Hashable {
    public let id: String
    public let name: String
    public let input: JSONValue
    public var result: String?
    public var isError: Bool
}

public struct TranscriptItem: Sendable, Hashable, Identifiable {
    public enum Content: Sendable, Hashable {
        case user(text: String, attachments: [Attachment])
        /// Assistant text; `streaming` while deltas arrive before the final message.
        case assistant(String, streaming: Bool)
        case thinking(String)
        case tool(ToolCall)
        /// An inline marker for an approval of this session.
        case approval(id: String, kind: ApprovalKind, status: ApprovalStatus)
        case result(TurnResult)
        /// A short line such as an interruption, a failure or an opened pull request.
        case notice(String)
    }

    public let id: String
    public var content: Content
    /// The stored event the item came from; nil while text streams.
    public var eventID: Int?
}

/// A request to show an event of the transcript, such as a search hit's.
public struct TranscriptFocus: Sendable, Hashable {
    public let eventID: Int
    /// Tells apart two requests for the same event.
    public let serial: Int
}

/// One session's transcript, built from its stored history plus live events.
@MainActor @Observable
public final class TranscriptStore {
    static let streamingID = "streaming"

    /// Where the history comes from.
    public enum Source: Sendable {
        case session
        /// A Claude Code chat's read-only history, read whole on each load.
        case claudeChat
    }

    /// Events loaded on each side of a focused event, and per Load earlier or newer.
    public static let pageSize = 100

    /// The session id, or the Claude Code chat id.
    public let sessionID: String
    public let source: Source
    public private(set) var items: [TranscriptItem] = []
    public private(set) var isLoaded = false
    /// The last stored event applied; replays and duplicates at or below it are skipped.
    public private(set) var lastEventID = 0
    /// Older events exist before the loaded ones (only after loading a page).
    public private(set) var hasOlder = false
    /// Newer events exist after the loaded ones; live events wait until they are loaded.
    public private(set) var hasNewer = false
    /// The event the view should scroll to and highlight next.
    public private(set) var focus: TranscriptFocus?
    /// Live events that arrived before the history.
    private var early: [Event] = []
    /// The stored events applied, oldest first, to rebuild the items with older ones.
    private var history: [Event] = []
    private var focusSerial = 0

    let api: any HarnessAPI

    public init(sessionID: String, api: any HarnessAPI, source: Source = .session) {
        self.sessionID = sessionID
        self.api = api
        self.source = source
    }

    /// Loads the history: all of it, newer events after a reload, or the page around a
    /// focus requested before the first load.
    public func load() async throws {
        let events: [Event]
        switch source {
        case .session:
            if !isLoaded, let focus {
                try await loadPage(around: focus.eventID)
                return
            }
            events = try await api.sessionEvents(sessionID, after: lastEventID)
            hasNewer = false
        case .claudeChat:
            // Claude Code may have rewound or compacted it since, so start over.
            events = try await api.claudeChatEvents(sessionID)
            items = []
            history = []
            lastEventID = 0
        }
        events.forEach(apply)
        finishLoading()
    }

    /// The items the transcript shows: successful turn results and empty (redacted)
    /// thinking are left out.
    public var visibleItems: [TranscriptItem] {
        items.filter { item in
            switch item.content {
            case .result(let result): result.isError
            case .thinking(let text): !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            default: true
            }
        }
    }

    // MARK: Focus and pages

    /// Asks the view to show an event; a transcript not loaded yet loads only the page
    /// around it.
    public func requestFocus(event: Int) {
        focusSerial += 1
        focus = TranscriptFocus(eventID: event, serial: focusSerial)
    }

    /// The item to scroll to for the requested focus, loading the page around the event
    /// when it is outside the loaded ones; the request is done after this. Nil when there
    /// is none, or before the first load.
    public func resolveFocus() async throws -> String? {
        guard isLoaded, let focus else { return nil }
        self.focus = nil
        if !holds(focus.eventID) {
            try await loadPage(around: focus.eventID)
        }
        return itemID(forEvent: focus.eventID)
    }

    /// The shown item for an event: the last one at or before it, since a tool result
    /// shows with its call; else the first one after it.
    public func itemID(forEvent event: Int) -> String? {
        let shown = visibleItems.compactMap { item in item.eventID.map { (item.id, $0) } }
        return (shown.last { $0.1 <= event } ?? shown.first)?.0
    }

    /// Loads the page of events before the oldest loaded one.
    public func loadOlder() async throws {
        guard hasOlder, let first = history.first?.id else { return }
        let older = try await api.sessionEvents(
            sessionID, after: 0, before: first, limit: Self.pageSize)
        hasOlder = older.count == Self.pageSize
        rebuild(older + history)
    }

    /// Loads the page of events after the newest loaded one.
    public func loadNewer() async throws {
        guard hasNewer else { return }
        let newer = try await api.sessionEvents(
            sessionID, after: lastEventID, before: nil, limit: Self.pageSize)
        hasNewer = newer.count == Self.pageSize
        newer.forEach(apply)
    }

    /// Whether the event is among the loaded ones, or would arrive live.
    private func holds(_ event: Int) -> Bool {
        let start = hasOlder ? history.first?.id : nil
        return event >= (start ?? 0) && (event <= lastEventID || !hasNewer)
    }

    /// Replaces the items with the events on each side of `event`, itself included.
    private func loadPage(around event: Int) async throws {
        let older = try await api.sessionEvents(
            sessionID, after: 0, before: event + 1, limit: Self.pageSize)
        let newer = try await api.sessionEvents(
            sessionID, after: event, before: nil, limit: Self.pageSize)
        hasOlder = older.count == Self.pageSize
        hasNewer = newer.count == Self.pageSize
        rebuild(older + newer)
        finishLoading()
    }

    private func finishLoading() {
        isLoaded = true
        // Text deltas from before the history are already in its final messages, and
        // events past a page that stops short of the newest are loaded with it later.
        if !hasNewer {
            early.filter { $0.id != nil }.forEach(apply)
        }
        early = []
    }

    /// Builds the items again from these stored events, keeping text that streams.
    private func rebuild(_ events: [Event]) {
        let streaming = items.last { $0.id == Self.streamingID }
        items = []
        history = []
        lastEventID = 0
        events.forEach(apply)
        if let streaming, !hasNewer {
            items.append(streaming)
        }
    }

    // MARK: Events

    public func receive(_ event: Event) {
        if !isLoaded {
            early.append(event)
        } else if !hasNewer {
            apply(event)
        }
    }

    func apply(_ event: Event) {
        if let id = event.id {
            guard id > lastEventID else { return }
            lastEventID = id
            history.append(event)
        }
        let key = event.id.map { "e\($0)" } ?? UUID().uuidString
        let eventID = event.id
        switch event.body {
        case .userMessage(let message):
            append(key, .user(text: message.text, attachments: message.attachments), eventID)
        case .message(let message) where message.parentToolUseID == nil:
            endStreaming()
            for (index, block) in message.blocks.enumerated() {
                add(block, id: "\(key)-\(index)", eventID: eventID)
            }
        case .delta(let text):
            stream(text)
        case .result(let result):
            endStreaming()
            append(key, .result(result), eventID)
        case .approvalCreated(let approval), .approvalResolved(let approval):
            mark(approval, eventID)
        case .sessionState(.interrupted, _):
            endStreaming()
            append(key, .notice("Interrupted"), eventID)
        case .sessionState(.failed, let error):
            endStreaming()
            append(key, .notice(error ?? "Failed"), eventID)
        case .gitFailed(let step, let stderr):
            append(key, .notice("git \(step) failed: \(stderr)"), eventID)
        case .prOpened(let url):
            append(key, .notice("Opened pull request \(url)"), eventID)
        default:
            break
        }
    }

    private func add(_ block: MessageBlock, id: String, eventID: Int?) {
        switch block {
        case .text(let text):
            append(id, .assistant(text, streaming: false), eventID)
        case .thinking(let text):
            append(id, .thinking(text), eventID)
        case .toolUse(let toolID, let name, let input):
            append(
                toolID,
                .tool(ToolCall(id: toolID, name: name, input: input, result: nil, isError: false)),
                eventID)
        case .toolResult(let toolID, let content, let isError):
            guard let index = items.firstIndex(where: { $0.id == toolID }),
                case .tool(var call) = items[index].content
            else { return }
            call.result = content
            call.isError = isError
            items[index].content = .tool(call)
        case .unknown:
            break
        }
    }

    private func stream(_ text: String) {
        if let last = items.last, last.id == Self.streamingID,
            case .assistant(let sofar, _) = last.content
        {
            items[items.count - 1].content = .assistant(sofar + text, streaming: true)
        } else {
            append(Self.streamingID, .assistant(text, streaming: true), nil)
        }
    }

    /// The final message replaces the streamed text.
    private func endStreaming() {
        items.removeAll { $0.id == Self.streamingID }
    }

    private func mark(_ approval: Approval, _ eventID: Int?) {
        let content = TranscriptItem.Content.approval(
            id: approval.id, kind: approval.kind, status: approval.status)
        if let index = items.firstIndex(where: { $0.id == approval.id }) {
            items[index].content = content
        } else {
            append(approval.id, content, eventID)
        }
    }

    private func append(_ id: String, _ content: TranscriptItem.Content, _ eventID: Int?) {
        items.append(TranscriptItem(id: id, content: content, eventID: eventID))
    }
}

/// The transcripts the app has opened, fed by live events.
@MainActor @Observable
public final class Transcripts {
    private var stores: [String: TranscriptStore] = [:]

    let api: any HarnessAPI

    public init(api: any HarnessAPI) {
        self.api = api
    }

    /// The transcript of a pane's chat (a session, or a Claude Code chat by its pane id);
    /// created empty the first time, then `load()` it.
    public func transcript(for pane: String) -> TranscriptStore {
        if let store = stores[pane] {
            return store
        }
        let store =
            ClaudeChat.chatID(ofPane: pane).map {
                TranscriptStore(sessionID: $0, api: api, source: .claudeChat)
            } ?? TranscriptStore(sessionID: pane, api: api)
        stores[pane] = store
        return store
    }

    /// The pane's transcript if it was opened before.
    public func existing(_ pane: String) -> TranscriptStore? {
        stores[pane]
    }

    public func receive(_ event: Event) {
        if case .sessionDeleted(let id) = event.body {
            stores[id] = nil
        } else if let id = event.sessionID {
            stores[id]?.receive(event)
        }
    }

    public func close(_ sessionID: String) {
        stores[sessionID] = nil
    }
}
