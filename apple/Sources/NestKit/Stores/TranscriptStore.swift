import Foundation
import Observation

/// A tool call of the main agent, with its result once it arrives.
public struct ToolCall: Sendable, Hashable {
    public let id: String
    public let name: String
    public let input: JSONValue
    public var result: String?
    public var isError: Bool
    /// Its turn ended without a result and no background task of it runs (D054).
    public var stopped = false
    /// An agent call's own messages, from `session.message` events naming it as their
    /// parent: what a pixie call shows when opened (B40).
    public var steps: [CallStep] = []

    /// The subagent an agent call ran, such as a pixie's slug; nil for other tools.
    public var subagentType: String? {
        guard ToolSummary.kind(of: name) == .agent else { return nil }
        return input["subagent_type"]?.stringValue
    }
}

/// A line of what a subagent did: its text, or a tool it called.
public struct CallStep: Sendable, Hashable, Identifiable {
    public enum Kind: Sendable, Hashable {
        case text(String)
        case tool(name: String, input: JSONValue)
    }

    public let id: String
    public let kind: Kind

    /// The text, or a tool call as one plain line: "Read src/app.ts".
    public var line: String {
        switch kind {
        case .text(let text): text
        case .tool(let name, let input):
            [name, ToolSummary.argument(tool: name, input: input)].filter { !$0.isEmpty }
                .joined(separator: " ")
        }
    }
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
        /// An inline marker for an approval of this session; `rejected` for a review the
        /// user rejected, whose line says the changes stay (B54).
        case approval(
            id: String, kind: ApprovalKind, status: ApprovalStatus, rejected: Bool = false)
        case result(TurnResult)
        /// The end of a turn whose length is known: "Worked for 1m 12s".
        case turnEnd(TurnEnd)
        /// A short line such as an interruption, a failure, an opened pull request or a
        /// notice from Claude Code.
        case notice(String)
        /// The daemon's report to a pixie that the chats it started finished (B41).
        case reportBack(String)
        /// A card in a pixie's chat for a chat it started or a pull request (B41).
        case pixieCard(PixieCard)
        /// "Report from habit <name>: <title>", the message that starts a pixie's turn
        /// after a habit run reported (B42).
        case habitReport(String)
    }

    public let id: String
    public var content: Content
    /// The stored event the item came from; nil while text streams.
    public var eventID: Int?
    /// The pixie that sent a user message into this chat (B41).
    public var fromPixie: String?
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
    /// Task list bookkeeping, which the Goals card shows instead.
    static let hiddenTools: Set<String> = ["TaskCreate", "TaskUpdate", "TaskList", "TaskGet"]

    /// The session id, or the Claude Code chat id.
    public let sessionID: String
    public let source: Source
    public private(set) var items: [TranscriptItem] = [] {
        didSet {
            visibleCache = nil
            entriesCache = nil
        }
    }
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
    /// The latest user message's event id. Event ids order the exchange where they can,
    /// so a step of the clock does not move tasks in or out of it (I-H).
    public private(set) var exchangeStartEvent: Int?
    /// The event that started or finished each background task, by tool use id.
    private var taskStarts: [String: Int] = [:]
    private var taskEnds: [String: Int] = [:]
    /// `visibleItems` and `entries(live:background:)` as last computed for these items.
    @ObservationIgnored private var visibleCache: [TranscriptItem]?
    @ObservationIgnored private var entriesCache:
        (live: Bool, background: Set<String>, pixies: Set<String>, entries: [TranscriptEntry])?
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
    /// The last turn's error result, while no other turn started since: the failed state
    /// that follows says why in its place.
    private var lastErrorResult: String?
    /// Stored live events that arrived before the history, while a load runs, or after a
    /// catch-up failed; deltas are not kept, as their final messages are stored too.
    private(set) var held: [Event] = []
    /// A catch-up failed, so events may be missing before the live ones: those wait, and
    /// the next catch-up or opening loads again.
    private var behind = false
    /// Loads in flight; live events wait for them (see `holdingLiveEvents`).
    private var loads = 0
    /// The stored events applied, oldest first, to rebuild the items with older ones.
    private var history: [Event] = []
    private var focusSerial = 0

    let api: any NestAPI

    public init(sessionID: String, api: any NestAPI, source: Source = .session) {
        self.sessionID = sessionID
        self.api = api
        self.source = source
    }

    /// Loads the history: all of it, newer events after a reload, or the page around a
    /// focus requested before the first load.
    public func load() async throws {
        try await holdingLiveEvents {
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
                exchangeStartEvent = nil
                taskStarts = [:]
                taskEnds = [:]
            }
            events.forEach(apply)
            finishLoading()
        }
    }

    /// What the chat shows while `catchUpFailure` is set, with Retry.
    public static let catchUpFailedText = "Could not catch up with this chat"

    /// Why the last catch-up of the loaded transcript failed; live events wait meanwhile,
    /// so the chat says so instead of freezing silently (audit BUG-101).
    public private(set) var catchUpFailure: String?

    /// Loads again after a connect: when the last load failed, and, when the connection
    /// may have missed events (`missed`), the ones after the newest loaded. A transcript
    /// with newer pages still to load gets them with those pages.
    public func catchUp(missed: Bool) async {
        guard loads == 0, !isLoaded || behind || (missed && source == .session && !hasNewer)
        else { return }
        await loadMissed()
    }

    /// Retry after a failed catch-up.
    public func retryCatchUp() async {
        guard loads == 0 else { return }
        await loadMissed()
    }

    private func loadMissed() async {
        // Until the load succeeds, events may be missing before the live ones.
        behind = isLoaded
        do {
            try await load()
        } catch {
            if isLoaded {
                catchUpFailure = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
    }

    /// Opening the transcript should load it: it never loaded, or a catch-up failed.
    public var needsLoad: Bool { !isLoaded || behind }

    /// The items the transcript shows: successful turn results and empty (redacted)
    /// thinking of unknown length are left out. Kept until the items change, as views read
    /// it on every update (IMP-11).
    public var visibleItems: [TranscriptItem] {
        let items = self.items
        if let visibleCache {
            return visibleCache
        }
        let visible = items.filter { item in
            switch item.content {
            case .result(let result): result.isError
            case .thinking(let text, let duration):
                duration != nil || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            default: true
            }
        }
        visibleCache = visible
        return visible
    }

    /// The transcript's rows (`TranscriptGrouping.entries`), kept until the items, the
    /// turn's liveness, the running background tasks or the pixies' slugs change.
    public func entries(live: Bool, background: Set<String> = [], pixies: Set<String> = [])
        -> [TranscriptEntry]
    {
        let visible = visibleItems
        if let cached = entriesCache, cached.live == live, cached.background == background,
            cached.pixies == pixies
        {
            return cached.entries
        }
        let entries = TranscriptGrouping.entries(
            visible, live: live, background: background, pixies: pixies)
        entriesCache = (live, background, pixies, entries)
        return entries
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
    /// latest user message is known, only those still at work. A task whose start or end
    /// the transcript holds is placed by event id, others by time.
    public func exchange(of summary: BackgroundSummary) -> BackgroundSummary {
        guard knowsExchange else { return summary.exchange(since: .distantFuture) }
        guard let date = exchangeStartedAt else { return summary }
        return summary.exchange(
            since: ExchangeStart(
                date: date, event: exchangeStartEvent, starts: taskStarts, ends: taskEnds))
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
        try await holdingLiveEvents {
            let newer = try await api.sessionEvents(
                sessionID, after: lastEventID, before: nil, limit: Self.pageSize)
            hasNewer = newer.count == Self.pageSize
            newer.forEach(apply)
        }
    }

    /// Whether the event is among the loaded ones, or would arrive live.
    private func holds(_ event: Int) -> Bool {
        let start = hasOlder ? history.first?.id : nil
        return event >= (start ?? 0) && (event <= lastEventID || !hasNewer)
    }

    /// Replaces the items with the events on each side of `event`, itself included.
    private func loadPage(around event: Int) async throws {
        try await holdingLiveEvents {
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
    }

    /// Reads back from the newest events, a page at a time, to the latest user message
    /// after `event`; without one there, the page's own latest message starts the exchange.
    private func findExchange(after event: Int) async throws {
        var before: Int? = .max
        while let end = before {
            let events = try await api.sessionEvents(
                sessionID, after: event, before: end, limit: Self.pageSize)
            if let message = events.last(where: \.isUserMessage) {
                noteUserMessage(message)
                return
            }
            before = events.count == Self.pageSize ? events.first?.id : nil
        }
    }

    private func finishLoading() {
        isLoaded = true
        knowsExchange = true
        behind = false
        catchUpFailure = nil
    }

    /// Runs a load while live events wait, so that none is lost meanwhile and none is
    /// applied ahead of the loaded events (which would then be skipped as already seen).
    /// Once loaded, the stored ones that waited apply; text deltas are dropped, as their
    /// final messages are stored too, and events past a page that stops short of the newest
    /// are loaded with it later.
    private func holdingLiveEvents(_ load: () async throws -> Void) async rethrows {
        loads += 1
        defer {
            loads -= 1
            if loads == 0 && isLoaded && !behind {
                if !hasNewer {
                    held.forEach(apply)
                }
                held = []
            }
        }
        try await load()
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
        lastErrorResult = nil
    }

    // MARK: Events

    public func receive(_ event: Event) {
        if case .thinking(let active) = event.body {
            reportsThinking = true
            thinkingLive = active
            return
        }
        if event.isUserMessage {
            noteUserMessage(event)
            knowsExchange = true
        }
        if !isLoaded || loads > 0 || behind {
            if event.id != nil {
                held.append(event)
            }
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
            noteUserMessage(event)
            if message.origin == .reportBack {
                append(key, .reportBack(message.text), eventID)
            } else if message.origin == .report {
                append(key, .habitReport(message.text), eventID)
            } else {
                append(
                    key, .user(text: message.text, attachments: message.attachments), eventID,
                    fromPixie: message.fromPixie)
            }
        case .message(let message) where message.parentToolUseID == nil:
            noteTaskStarts(message, eventID)
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
            lastErrorResult = result.isError ? key : nil
        case .sessionState(.running, _):
            startTurn(at: event.ts, marked: event.payload["turn_start"]?.boolValue == true)
        case .sessionState(.idle, _):
            settleTurn(key, eventID, event, stopped: false)
        case .approvalCreated(let approval), .approvalResolved(let approval):
            mark(approval, eventID)
        case .sessionState(.interrupted, _):
            endStreaming()
            if !settleTurn(key, eventID, event, stopped: true) {
                append(key, .notice("Interrupted"), eventID)
            }
        case .sessionState(.failed, let error):
            endStreaming()
            settleTurn(key, eventID, event, stopped: true)
            if let result = lastErrorResult {
                items.removeAll { $0.id == result }
                lastErrorResult = nil
            }
            append(key, .notice(error.map { "Failed: \($0)" } ?? "Failed"), eventID)
        case .message(let message):
            noteTaskStarts(message, eventID)
            if let parent = message.parentToolUseID {
                addSteps(message.blocks, to: parent, key: key)
            }
        case .agentTask(let task):
            if task.phase == .finished, let tool = task.toolUseID, let eventID {
                taskEnds[tool] = eventID
            }
        case .gitFailed(let step, let stderr):
            append(key, .notice("git \(step) failed: \(stderr)"), eventID)
        case .prOpened(let url):
            append(key, .notice("Opened pull request \(url)"), eventID)
        case .sessionNotice(let text):
            append(key, .notice(text), eventID)
        case .pixieCard(let card):
            append(key, .pixieCard(card), eventID)
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
        case .toolUse(_, let name, _) where Self.hiddenTools.contains(name):
            break
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

    /// A subagent's text and tool calls go with its agent call; its thinking and the
    /// results of its own tools are not shown. A call this page does not hold drops them.
    private func addSteps(_ blocks: [MessageBlock], to parent: String, key: String) {
        guard let index = items.firstIndex(where: { $0.id == parent }),
            case .tool(var call) = items[index].content, ToolSummary.kind(of: call.name) == .agent
        else { return }
        for (offset, block) in blocks.enumerated() {
            let id = "\(key)-\(offset)"
            switch block {
            case .text(let text) where !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty:
                call.steps.append(CallStep(id: id, kind: .text(text)))
            case .toolUse(_, let name, let input):
                call.steps.append(CallStep(id: id, kind: .tool(name: name, input: input)))
            default:
                break
            }
        }
        items[index].content = .tool(call)
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

    /// User messages come in order, so the latest one seen anywhere starts the exchange:
    /// the one with the highest event id, or the latest time for one without an id.
    private func noteUserMessage(_ event: Event) {
        guard let id = event.id else {
            exchangeStartedAt = max(exchangeStartedAt ?? event.ts, event.ts)
            return
        }
        guard id >= exchangeStartEvent ?? id else { return }
        exchangeStartEvent = id
        exchangeStartedAt = event.ts
    }

    /// Remembers which event made each tool call, as background tasks go by their call.
    private func noteTaskStarts(_ message: AgentMessage, _ eventID: Int?) {
        guard let eventID else { return }
        for case .toolUse(let id, _, _) in message.blocks where taskStarts[id] == nil {
            taskStarts[id] = eventID
        }
    }

    // MARK: Turns

    /// A user message, or the agent going on by itself, opens a turn unless one is open;
    /// the daemon's `turn_start` mark always starts one.
    private func startTurn(at date: Date, marked: Bool = false) {
        guard turnStartedAt == nil || marked else { return }
        turnStartedAt = date
        lastTurnEnd = nil
        lastErrorResult = nil
    }

    /// Ends the open turn with a line saying how long it took, preferring the engine's
    /// duration, else (when `measure` allows) the time since its start; a turn of unknown
    /// length gets no line. Whether it got one.
    @discardableResult
    private func endTurn(
        _ key: String, _ eventID: Int?, at date: Date, durationMS: Int?, stopped: Bool,
        measure: Bool = true
    ) -> Bool {
        let measured = measure ? turnStartedAt.map { Int(date.timeIntervalSince($0) * 1000) } : nil
        turnStartedAt = nil
        lastTurnEnd = nil
        guard let duration = durationMS ?? measured else { return false }
        let id = "\(key)-end"
        append(id, .turnEnd(TurnEnd(durationMS: duration, stopped: stopped)), eventID)
        lastTurnEnd = id
        return true
    }

    /// The session left the turn (idle, interrupted or failed), with the daemon's measure
    /// of the turn when it sends one: the open turn ends, or the turn its result just
    /// ended takes that measure and, when stopped, says so. Whether the turn has a line
    /// with its length. A measure sent as null, or an interruption without one (the
    /// daemon's recovery after a restart), means the length is unknown: the time between
    /// the events would count the downtime too. Only older daemons' ends without the
    /// field are timed from the turn's start.
    @discardableResult
    private func settleTurn(_ key: String, _ eventID: Int?, _ event: Event, stopped: Bool)
        -> Bool
    {
        let field = event.payload["duration_ms"]
        let duration = field?.numberValue.map { Int($0) }
        if turnStartedAt != nil {
            let measure = field == nil && event.payload["state"]?.stringValue != "interrupted"
            return endTurn(
                key, eventID, at: event.ts, durationMS: duration, stopped: stopped,
                measure: measure)
        }
        guard let id = lastTurnEnd, let index = items.firstIndex(where: { $0.id == id }),
            case .turnEnd(var end) = items[index].content
        else { return false }
        end.durationMS = duration ?? end.durationMS
        end.stopped = end.stopped || stopped
        items[index].content = .turnEnd(end)
        return true
    }

    /// The final message replaces the streamed text.
    private func endStreaming() {
        items.removeAll { $0.id == Self.streamingID }
    }

    private func mark(_ approval: Approval, _ eventID: Int?) {
        let content = TranscriptItem.Content.approval(
            id: approval.id, kind: approval.kind, status: approval.status,
            rejected: approval.kind == .review
                && approval.resolution?["action"]?.stringValue == "rejected")
        if let index = items.firstIndex(where: { $0.id == approval.id }) {
            items[index].content = content
        } else {
            append(approval.id, content, eventID)
        }
    }

    private func append(
        _ id: String, _ content: TranscriptItem.Content, _ eventID: Int?,
        fromPixie: String? = nil
    ) {
        items.append(
            TranscriptItem(id: id, content: content, eventID: eventID, fromPixie: fromPixie))
    }
}

/// The transcripts the app has opened, fed by live events.
@MainActor @Observable
public final class Transcripts {
    private var stores: [String: TranscriptStore] = [:]

    let api: any NestAPI

    public init(api: any NestAPI) {
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

    /// Releases the transcripts of panes no workspace shows any more.
    public func keep(_ panes: Set<String>) {
        stores = stores.filter { panes.contains($0.key) }
    }

    /// After a connect: transcripts whose load failed load again, and when the connection
    /// did not resume (`missed`), loaded ones fetch the events they missed.
    public func catchUp(missed: Bool) async {
        for store in Array(stores.values) {
            await store.catchUp(missed: missed)
        }
    }
}
