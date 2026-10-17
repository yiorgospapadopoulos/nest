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
    /// Versions read, which never change.
    private var contents: [ArtifactSelection: ArtifactContent] = [:]
    @ObservationIgnored private var checks: [String: Task<Void, Never>] = [:]

    let api: any NestAPI

    public init(api: any NestAPI) {
        self.api = api
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
        selection = shown
        if contents[shown] == nil {
            contents[shown] = try await api.artifactContent(id, version: shown.version)
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
        if selection?.id == id {
            selection = nil
        }
    }
}
