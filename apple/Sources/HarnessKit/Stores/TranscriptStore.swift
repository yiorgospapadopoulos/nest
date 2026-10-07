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

/// How a turn ended: how long it worked, and whether it was interrupted or failed.
public struct TurnEnd: Sendable, Hashable {
    public var durationMS: Int
    public var stopped: Bool

    public init(durationMS: Int, stopped: Bool) {
        self.durationMS = durationMS
        self.stopped = stopped
    }
}

public struct TranscriptItem: Sendable, Hashable, Identifiable {
    public enum Content: Sendable, Hashable {
        case user(text: String, attachments: [Attachment])
        /// Assistant text; `streaming` while deltas arrive before the final message.
        case assistant(String, streaming: Bool)
        /// Thinking text, with how long it took when known.
        case thinking(String, durationMS: Int?)
        case tool(ToolCall)
        /// An inline marker for an approval of this session.
        case approval(id: String, kind: ApprovalKind, status: ApprovalStatus)
        case result(TurnResult)
        /// The end of a turn whose length is known: "Worked for 1m 12s".
        case turnEnd(TurnEnd)
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
    /// When the open turn started; nil between turns.
    public private(set) var turnStartedAt: Date?
    /// When the user's latest message was sent: the current exchange, whose background
    /// tasks the bar counts, began then. Turns the agent starts by itself stay in it. Kept
    /// apart from the loaded page, so a search hit's page does not move it back.
    public private(set) var exchangeStartedAt: Date?
    /// The latest user message is known: a load reached the newest events or looked it up,
    /// or one arrived live (nothing newer can come any other way).
    private var knowsExchange = false
    /// A main-agent thinking block runs, as the daemon's `session.thinking` reports.
    private var thinkingLive = false
    /// The daemon sends `session.thinking`; older daemons do not.
    private var reportsThinking = false
    /// The end of the last turn, while no other turn started since: an interruption or
    /// failure reported after the result marks it stopped.
    private var lastTurnEnd: String?
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
            reset()
            exchangeStartedAt = nil
        }
        events.forEach(apply)
        finishLoading()
    }

    /// The items the transcript shows: successful turn results and empty (redacted)
    /// thinking of unknown length are left out.
    public var visibleItems: [TranscriptItem] {
        items.filter { item in
            switch item.content {
            case .result(let result): result.isError
            case .thinking(let text, let duration):
                duration != nil || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            default: true
            }
        }
    }

    /// A thinking block runs: as the daemon reports, or for daemons that do not, the open
    /// turn's latest content is thinking.
    public var isThinking: Bool {
        if reportsThinking {
            return thinkingLive
        }
        guard turnStartedAt != nil, case .thinking = items.last?.content else { return false }
        return true
    }

    /// The background bar's tasks (see `BackgroundSummary.exchange(since:)`); until the
    /// latest user message is known, only those still at work.
    public func exchange(of summary: BackgroundSummary) -> BackgroundSummary {
        summary.exchange(since: knowsExchange ? exchangeStartedAt : .distantFuture)
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
        if hasNewer && !knowsExchange {
            try await findExchange(after: lastEventID)
        }
        finishLoading()
    }

    /// Reads back from the newest events, a page at a time, to the latest user message
    /// after `event`; without one there, the page's own latest message starts the exchange.
    private func findExchange(after event: Int) async throws {
        var before: Int? = .max
        while let end = before {
            let events = try await api.sessionEvents(
                sessionID, after: event, before: end, limit: Self.pageSize)
            if let message = events.last(where: \.isUserMessage) {
                noteUserMessage(at: message.ts)
                return
            }
            before = events.count == Self.pageSize ? events.first?.id : nil
        }
    }

    private func finishLoading() {
        isLoaded = true
        knowsExchange = true
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
        reset()
        events.forEach(apply)
        if let streaming, !hasNewer {
            items.append(streaming)
        }
    }

    private func reset() {
        items = []
        history = []
        lastEventID = 0
        turnStartedAt = nil
        lastTurnEnd = nil
    }

    // MARK: Events

    public func receive(_ event: Event) {
        if case .thinking(let active) = event.body {
            reportsThinking = true
            thinkingLive = active
            return
        }
        if event.isUserMessage {
            noteUserMessage(at: event.ts)
            knowsExchange = true
        }
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
        case .message, .result, .sessionState:
            // A thinking block's end may never come; the next message, result or state
            // ends it, as in the PWA.
            thinkingLive = false
        default:
            break
        }
        switch event.body {
        case .userMessage(let message):
            startTurn(at: event.ts)
            noteUserMessage(at: event.ts)
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
            endTurn(
                key, eventID, at: event.ts, durationMS: result.durationMS, stopped: result.isError)
            append(key, .result(result), eventID)
        case .sessionState(.running, _):
            startTurn(at: event.ts, marked: event.payload["turn_start"]?.boolValue == true)
        case .sessionState(.idle, _):
            settleTurn(key, eventID, event, stopped: false)
        case .approvalCreated(let approval), .approvalResolved(let approval):
            mark(approval, eventID)
        case .sessionState(.interrupted, _):
            endStreaming()
            settleTurn(key, eventID, event, stopped: true)
            append(key, .notice("Interrupted"), eventID)
        case .sessionState(.failed, let error):
            endStreaming()
            settleTurn(key, eventID, event, stopped: true)
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
        case .thinking(let text, let duration):
            append(id, .thinking(text, durationMS: duration), eventID)
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

    /// User messages come in order, so the latest one seen anywhere starts the exchange.
    private func noteUserMessage(at date: Date) {
        exchangeStartedAt = max(exchangeStartedAt ?? date, date)
    }

    // MARK: Turns

    /// A user message, or the agent going on by itself, opens a turn unless one is open;
    /// the daemon's `turn_start` mark always starts one.
    private func startTurn(at date: Date, marked: Bool = false) {
        guard turnStartedAt == nil || marked else { return }
        turnStartedAt = date
        lastTurnEnd = nil
    }

    /// Ends the open turn with a line saying how long it took, preferring the engine's
    /// duration; a turn of unknown start and length gets no line.
    private func endTurn(
        _ key: String, _ eventID: Int?, at date: Date, durationMS: Int?, stopped: Bool
    ) {
        let measured = turnStartedAt.map { Int(date.timeIntervalSince($0) * 1000) }
        turnStartedAt = nil
        lastTurnEnd = nil
        guard let duration = durationMS ?? measured else { return }
        let id = "\(key)-end"
        append(id, .turnEnd(TurnEnd(durationMS: duration, stopped: stopped)), eventID)
        lastTurnEnd = id
    }

    /// The session left the turn (idle, interrupted or failed), with the daemon's measure
    /// of the turn when it sends one: the open turn ends, or the turn its result just
    /// ended takes that measure and, when stopped, says so.
    private func settleTurn(_ key: String, _ eventID: Int?, _ event: Event, stopped: Bool) {
        let duration = event.payload["duration_ms"]?.numberValue.map { Int($0) }
        if turnStartedAt != nil {
            endTurn(key, eventID, at: event.ts, durationMS: duration, stopped: stopped)
        } else if let id = lastTurnEnd, let index = items.firstIndex(where: { $0.id == id }),
            case .turnEnd(var end) = items[index].content
        {
            end.durationMS = duration ?? end.durationMS
            end.stopped = end.stopped || stopped
            items[index].content = .turnEnd(end)
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
