import Foundation
import Observation

/// Which artifacts a list holds (B79).
public enum ArtifactQuery: Sendable, Hashable {
    /// The ones a chat saved.
    case chat(String)
    /// Every chat's of a project, deleted chats' too.
    case project(String)
    /// The ones a pixie's chat and habit runs saved.
    case pixie(String)
    /// Every pixie's.
    case pixies

    var filters: (repo: String?, sessionID: String?, pixieID: String?) {
        switch self {
        case .chat(let id): (nil, id, nil)
        case .project(let repo): (repo, nil, nil)
        case .pixie(let id): (nil, nil, id)
        case .pixies: (nil, nil, nil)
        }
    }

    public func matches(_ artifact: Artifact) -> Bool {
        switch self {
        case .chat(let id): artifact.sessionID == id
        case .project(let repo): artifact.repo == repo
        case .pixie(let id): artifact.pixieID == id
        case .pixies: artifact.pixieID != nil
        }
    }

    /// The scope switch's label.
    public var label: String {
        switch self {
        case .chat: "This chat"
        case .project: "Whole project"
        case .pixie: "This pixie"
        case .pixies: "All pixies"
        }
    }
}

/// What the Artifacts view lists: the focused chat's or pixie's (`narrow`) with a switch
/// to the wider list, or only the wider one when nothing is focused.
public struct ArtifactScope: Sendable, Hashable {
    public var narrow: ArtifactQuery?
    public var wide: ArtifactQuery

    public init(narrow: ArtifactQuery?, wide: ArtifactQuery) {
        self.narrow = narrow
        self.wide = wide
    }
}

/// The artifact and version the reader shows.
public struct ArtifactSelection: Sendable, Hashable {
    public let id: String
    public let version: Int

    public init(id: String, version: Int) {
        self.id = id
        self.version = version
    }
}

/// Whether a transcript card's artifact is still there.
public enum ArtifactAvailability: Sendable, Hashable {
    case unknown, available, deleted
}

/// The artifacts the app has listed or opened, the unseen count for the badge, and what
/// the Artifacts view shows (B79). Events keep it current; a reconnect reads it again.
@MainActor @Observable
public final class ArtifactsStore {
    /// Artifacts whose latest version the user has not opened, in every project.
    public private(set) var unseen = 0
    /// What the view lists; nil until a view shows.
    public private(set) var scope: ArtifactScope?
    /// The view lists the wide query, by choice or since nothing is focused.
    public private(set) var showsWide = false
    public private(set) var selection: ArtifactSelection?
    /// Ids that answered "not found" or were deleted.
    public private(set) var deleted: Set<String> = []
    /// Every artifact read so far, by id.
    private var known: [String: Artifact] = [:]
    /// The loaded lists, as ids newest first.
    private var lists: [ArtifactQuery: [String]] = [:]
    /// Versions read; their content never changes, the storage built into their page may.
    private var contents: [ArtifactSelection: ArtifactContent] = [:]
    @ObservationIgnored private var checks: [String: Task<Void, Never>] = [:]
    /// How much each artifact's page stored, for the ones read (B88).
    private var storageSizes: [String: Int] = [:]
    /// Open pages listening for storage changes, by token: the artifact and the handler.
    @ObservationIgnored private var storageListeners:
        [UUID: (id: String, handler: (ArtifactStorageChange) -> Void)] = [:]

    /// Asks running from this app, by artifact.
    private var localAsks: [String: Int] = [:]
    /// Artifacts whose ask another reader or device started.
    private var remoteAsks: Set<String> = []
    private var askCounts: [String: ArtifactAskCount] = [:]
    /// The usage pages read, and when, kept for a minute.
    @ObservationIgnored private var usage:
        (read: Date, limits: UsageLimits, today: UsagePeriod, week: UsagePeriod)?
    @ObservationIgnored private var usageListeners: [UUID: (ArtifactBridge.Value) -> Void] = [:]
    static let usageFreshness: TimeInterval = 60

    let api: any NestAPI
    let calendar: Calendar
    let now: @Sendable () -> Date

    public init(
        api: any NestAPI, calendar: Calendar = .current,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.api = api
        self.calendar = calendar
        self.now = now
    }

    // MARK: Reading

    public func artifact(_ id: String) -> Artifact? {
        known[id]
    }

    /// The query's artifacts newest first, or nil until it is loaded.
    public func list(_ query: ArtifactQuery) -> [Artifact]? {
        lists[query]?.compactMap { known[$0] }
    }

    public func content(_ selection: ArtifactSelection) -> ArtifactContent? {
        contents[selection]
    }

    public func availability(of id: String) -> ArtifactAvailability {
        deleted.contains(id) ? .deleted : known[id] == nil ? .unknown : .available
    }

    /// The query the view lists now.
    public var query: ArtifactQuery? {
        guard let scope else { return nil }
        return showsWide ? scope.wide : scope.narrow ?? scope.wide
    }

    public var selected: Artifact? { selection.flatMap { known[$0.id] } }

    public var selectedContent: ArtifactContent? { selection.flatMap { contents[$0] } }

    // MARK: Loading

    public func loadUnseen() async throws {
        unseen = try await api.unseenArtifacts()
    }

    public func load(_ query: ArtifactQuery) async throws {
        let filters = query.filters
        // Every pixie's comes from the unfiltered list.
        let artifacts = try await api.artifacts(
            repo: filters.repo, sessionID: filters.sessionID, pixieID: filters.pixieID
        ).filter(query.matches)
        for artifact in artifacts {
            known[artifact.id] = artifact
        }
        lists[query] = artifacts.map(\.id)
    }

    /// After a reconnect: the count, every loaded list and the open artifact again.
    public func reload() async throws {
        try await loadUnseen()
        for query in lists.keys {
            try await load(query)
        }
        if let selection {
            try? await fetch(selection.id)
        }
    }

    /// Reads one artifact; "not found" forgets it and marks it deleted.
    private func fetch(_ id: String) async throws {
        do {
            known[id] = try await api.artifact(id).artifact
        } catch APIError.notFound(let detail) {
            forget(id)
            throw APIError.notFound(detail)
        }
    }

    /// A transcript card's artifact, read once, so the card knows whether it was deleted;
    /// cards of the same artifact share the read.
    public func check(_ id: String) async {
        guard availability(of: id) == .unknown else { return }
        if let running = checks[id] {
            await running.value
            return
        }
        let task = Task { _ = try? await fetch(id) }
        checks[id] = task
        await task.value
        checks[id] = nil
    }

    // MARK: The view

    /// The view shows this scope: a new one starts on its narrow list.
    public func show(_ scope: ArtifactScope) {
        guard self.scope != scope else { return }
        self.scope = scope
        showsWide = false
    }

    /// The scope switch: the wide list or the narrow one. A selection the new list lacks
    /// moves to its newest artifact, or away when it has none.
    public func setWide(_ wide: Bool) async throws {
        showsWide = wide
        guard let query else { return }
        if lists[query] == nil {
            try await load(query)
        }
        try await keepSelectionListed()
    }

    /// Loads the listed query; a selection it lacks, or none, moves to its newest artifact.
    public func open() async throws {
        guard let query else { return }
        try await load(query)
        try await keepSelectionListed()
    }

    private func keepSelectionListed() async throws {
        if let selection, let query, lists[query]?.contains(selection.id) != true {
            self.selection = nil
        }
        try await selectNewestIfNone()
    }

    private func selectNewestIfNone() async throws {
        guard selection == nil, let query, let newest = lists[query]?.first else { return }
        try await select(newest)
    }

    /// Shows a version in the reader, the latest when none is named; showing the latest
    /// marks it seen.
    public func select(_ id: String, version: Int? = nil) async throws {
        if known[id] == nil {
            try await fetch(id)
        }
        guard let artifact = known[id] else { return }
        let shown = ArtifactSelection(
            id: id, version: min(max(version ?? artifact.latestVersion, 1), artifact.latestVersion))
        let moved = selection != shown
        selection = shown
        if moved || contents[shown] == nil {
            // A page carries what it stored when it was read (B88), so it is read again
            // each time the reader moves to it; the one read before stays if that fails.
            let kept = contents[shown]
            contents[shown] = nil
            do {
                contents[shown] = try await api.artifactContent(id, version: shown.version)
            } catch {
                contents[shown] = kept
                if kept == nil {
                    throw error
                }
            }
        }
        if selection == shown, shown.version == known[id]?.latestVersion,
            known[id]?.seen == false
        {
            await markSeen(id)
        }
    }

    /// The version stepper: the previous (-1) or next (1) version.
    public func step(by offset: Int) async throws {
        guard let selection, let artifact = known[selection.id] else { return }
        let version = selection.version + offset
        guard (1...artifact.latestVersion).contains(version) else { return }
        try await select(selection.id, version: version)
    }

    public func canStep(by offset: Int) -> Bool {
        guard let selection, let artifact = known[selection.id] else { return false }
        return (1...artifact.latestVersion).contains(selection.version + offset)
    }

    /// Seen at once; the count drops unless an event already counted it.
    private func markSeen(_ id: String) async {
        guard (try? await api.markArtifactSeen(id)) != nil, known[id]?.seen == false else {
            return
        }
        known[id]?.seen = true
        unseen = max(0, unseen - 1)
    }

    /// A page asked to save a document it is not, or not the latest version of.
    public struct SaveRefused: Error {}

    /// The user's edit of the document `page` shows, saved as a new version (B88); the
    /// reader moves to it if it still shows that page. Only the latest version of a
    /// document saves. Answers the new version.
    public func saveDocument(_ page: ArtifactSelection, content: String, baseVersion: Int)
        async throws -> Int
    {
        guard let artifact = known[page.id], artifact.kind == .document,
            page.version == artifact.latestVersion
        else { throw SaveRefused() }
        let saved = try await api.saveArtifactVersion(
            page.id, content: content, baseVersion: baseVersion)
        if var current = known[page.id], saved.version > current.latestVersion {
            current.latestVersion = saved.version
            current.versionCount += 1
            current.title = saved.title
            current.updatedAt = saved.createdAt
            known[page.id] = current
        }
        if selection == page {
            try? await select(page.id, version: saved.version)
        }
        return saved.version
    }

    // MARK: What pages store (B88)

    /// Bytes the artifact's page stored, 0 until read.
    public func storageSize(of id: String) -> Int {
        storageSizes[id] ?? 0
    }

    public func loadStorage(_ id: String) async throws {
        storageSizes[id] = try await api.artifactStorage(id).size
    }

    /// A page's write, or the reader's "Clear page data"; answers the new size. A clear
    /// reaches open pages through the daemon's event.
    @discardableResult
    public func writeStorage(_ id: String, _ change: ArtifactStorageChange) async throws -> Int {
        let size: Int
        switch change {
        case .write(let set, let remove):
            size = try await api.writeArtifactStorage(id, set: set, remove: remove)
        case .clear:
            try await api.clearArtifactStorage(id)
            size = 0
        }
        storageSizes[id] = size
        return size
    }

    /// Calls the handler with each storage change the daemon reports for the artifact,
    /// until `stopObserving` with the answered token.
    public func observeStorage(
        _ id: String, _ handler: @escaping (ArtifactStorageChange) -> Void
    ) -> UUID {
        let token = UUID()
        storageListeners[token] = (id, handler)
        return token
    }

    public func stopObserving(_ token: UUID) {
        storageListeners[token] = nil
    }

    private func storageChanged(_ event: ArtifactStorageEvent) {
        for listener in storageListeners.values where listener.id == event.artifactID {
            listener.handler(event.change)
        }
        let id = event.artifactID
        if storageSizes[id] != nil {
            Task { try? await loadStorage(id) }
        }
    }

    // MARK: Usage and asks (B88)

    /// What `nest.usage()` answers: read again when the last read is a minute old.
    public func pageUsage() async throws -> ArtifactBridge.Value {
        let at = now()
        if let usage, at.timeIntervalSince(usage.read) < Self.usageFreshness {
            return ArtifactPageUsage.value(
                limits: usage.limits, today: usage.today, week: usage.week)
        }
        let parts = calendar.dateComponents([.year, .month, .day], from: at)
        let day = CalendarDay(year: parts.year!, month: parts.month!, day: parts.day!)
        let limits = try await api.usageLimits()
        let today = try await api.usagePeriod(unit: .day, date: day)
        let week = try await api.usagePeriod(unit: .week, date: day)
        usage = (at, limits, today, week)
        return ArtifactPageUsage.value(limits: limits, today: today, week: week)
    }

    /// Calls the handler with a fresh snapshot each time the limits change, once pages
    /// read their usage.
    public func observeUsage(_ handler: @escaping (ArtifactBridge.Value) -> Void) -> UUID {
        let token = UUID()
        usageListeners[token] = handler
        return token
    }

    public func stopObservingUsage(_ token: UUID) {
        usageListeners[token] = nil
    }

    /// Windows from the engine replace the read ones; it may report only one of them.
    private func usageChanged(_ update: UsageLimits) {
        guard var read = usage else { return }
        var limits = read.limits
        limits.fiveHour = update.fiveHour ?? limits.fiveHour
        limits.sevenDay = update.sevenDay ?? limits.sevenDay
        read.limits = limits
        usage = read
        let value = ArtifactPageUsage.value(limits: limits, today: read.today, week: read.week)
        for listener in usageListeners.values {
            listener(value)
        }
    }

    /// Today's asks for the page are used: the message says when more come.
    public struct AskBudgetUsed: Error, Equatable {
        public let message: String
    }

    /// Today's asks of the artifact, for the reader's line once it asked at least once.
    public func loadAsks(_ id: String) async throws {
        let status = try await api.askStatus(id)
        if status.used > 0 {
            askCounts[id] = ArtifactAskCount(remaining: status.remaining, limit: status.limit)
        }
    }

    /// A page's ask to Claude, shown as running in the reader until it answers. A used-up
    /// day is `AskBudgetUsed`, naming the reset time from the ask status.
    public func ask(_ id: String, prompt: String, system: String?) async throws
        -> ArtifactAnswer
    {
        localAsks[id, default: 0] += 1
        defer {
            if let count = localAsks[id], count > 1 {
                localAsks[id] = count - 1
            } else {
                localAsks[id] = nil
            }
        }
        do {
            let answer = try await api.askArtifact(id, prompt: prompt, system: system)
            askCounts[id] = ArtifactAskCount(remaining: answer.remaining, limit: answer.limit)
            return answer
        } catch APIError.rateLimited {
            let status = try? await api.askStatus(id)
            if let status {
                askCounts[id] = ArtifactAskCount(remaining: status.remaining, limit: status.limit)
            }
            throw AskBudgetUsed(message: budgetMessage(status?.resetsAt))
        }
    }

    /// "Today's asks for this page are used up. Resets 06:05.", in local time.
    private func budgetMessage(_ resetsAt: Date?) -> String {
        let used = "Today\u{2019}s asks for this page are used up."
        guard let resetsAt else { return used }
        let hour = calendar.component(.hour, from: resetsAt)
        let minute = calendar.component(.minute, from: resetsAt)
        return used + String(format: " Resets %02d:%02d.", hour, minute)
    }

    public func isAsking(_ id: String) -> Bool {
        localAsks[id] != nil || remoteAsks.contains(id)
    }

    /// Today's asks, once the artifact asked while the app ran.
    public func askCount(of id: String) -> ArtifactAskCount? {
        askCounts[id]
    }

    private func askChanged(_ event: ArtifactAskEvent) {
        let id = event.artifactID
        askCounts[id] = ArtifactAskCount(remaining: event.remaining, limit: event.limit)
        if event.state == .started {
            remoteAsks.insert(id)
        } else {
            remoteAsks.remove(id)
        }
    }

    public func delete(_ id: String) async throws {
        try await api.deleteArtifact(id)
        if known[id]?.seen == false {
            unseen = max(0, unseen - 1)
        }
        forget(id)
        try await selectNewestIfNone()
    }

    // MARK: Events

    public func apply(_ event: Event) {
        switch event.body {
        case .artifactSaved(let saved):
            unseen = saved.unseen
            let artifact = saved.artifact
            known[artifact.id] = artifact
            for (query, ids) in lists where query.matches(artifact) {
                lists[query] = [artifact.id] + ids.filter { $0 != artifact.id }
            }
        case .artifactSeen(let id, let count):
            unseen = count
            known[id]?.seen = true
        case .artifactDeleted(let id, let count):
            unseen = count
            forget(id)
        case .artifactStorage(let change):
            storageChanged(change)
        case .artifactAsk(let event):
            askChanged(event)
        case .usageUpdated(let update):
            usageChanged(update)
        case .sessionDeleted(let session):
            markChatDeleted { $0.sessionID == session }
        case .pixieDeleted(let pixie):
            markChatDeleted { $0.pixieID == pixie }
        default:
            break
        }
    }

    private func markChatDeleted(_ matches: (Artifact) -> Bool) {
        for (id, artifact) in known where matches(artifact) {
            known[id]?.chatDeleted = true
        }
    }

    private func forget(_ id: String) {
        deleted.insert(id)
        known[id] = nil
        for (query, ids) in lists {
            lists[query] = ids.filter { $0 != id }
        }
        contents = contents.filter { $0.key.id != id }
        storageSizes[id] = nil
        if selection?.id == id {
            selection = nil
        }
    }
}
