import Foundation
import Observation

/// The user's pixies, in the order they set, with the actions of the Pixies section (D072).
@MainActor @Observable
public final class PixiesStore {
    /// Every pixie, hidden ones too, sorted by position.
    public private(set) var pixies: [Pixie] = []

    let api: any HarnessAPI

    /// Each pixie's last save; the next one waits for it, so saves reach the daemon in order.
    private var saves: [String: Task<Pixie, any Error>] = [:]
    /// How many saves of a pixie have not answered yet.
    private var unsaved: [String: Int] = [:]
    /// What the daemon last said a pixie is, kept while its saves run and shown after the
    /// last one: a quick second change is never undone by the first one's answer.
    private var confirmed: [String: Pixie] = [:]
    /// The last reorder; the next one waits for it, so orders reach the daemon in turn.
    private var reorders: Task<[Pixie], any Error>?
    /// How many reorders have not answered yet.
    private var unordered = 0
    /// The order the daemon last confirmed, shown once the last reorder answers.
    private var confirmedOrder: [String] = []

    public init(api: any HarnessAPI) {
        self.api = api
    }

    /// The pixies the app shows: hidden ones are left out.
    public var visible: [Pixie] {
        pixies.filter { !$0.hidden }
    }

    public func load() async throws {
        pixies = Self.sorted(try await api.pixies())
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .pixieUpdated(let pixie): receive(pixie)
        case .pixieDeleted(let id):
            pixies.removeAll { $0.id == id }
            confirmed[id] = nil
        default: break
        }
    }

    // MARK: Actions

    @discardableResult
    public func create(_ request: CreatePixieRequest) async throws -> Pixie {
        store(try await api.createPixie(request))
    }

    /// Shows the change at once and saves it after the pixie's earlier saves. Once the
    /// last save answers, the pixie is what the daemon says: a refused change goes back.
    /// Answers the daemon's pixie for this save, whatever later saves show meanwhile.
    @discardableResult
    public func update(_ id: String, _ request: UpdatePixieRequest) async throws -> Pixie {
        if let shown = pixies.first(where: { $0.id == id }) {
            if unsaved[id] == nil {
                confirmed[id] = shown
            }
            store(shown.applying(request))
        }
        unsaved[id, default: 0] += 1
        let previous = saves[id]
        let save = Task {
            _ = try? await previous?.value
            return try await api.updatePixie(id, request)
        }
        saves[id] = save
        defer { settle(id, save) }
        let saved = try await save.value
        confirmed[id] = Self.newest(confirmed[id], saved)
        return saved
    }

    /// A save of the pixie is running or waiting its turn.
    public func isSaving(_ id: String) -> Bool {
        unsaved[id] != nil
    }

    /// Moves a pixie to where another one is: below it when moved down the list, above it
    /// when moved up. The list shows the new order at once and goes back if the daemon
    /// refuses it.
    public func move(_ id: String, onto target: String) async throws {
        guard id != target, let from = pixies.firstIndex(where: { $0.id == id }),
            let to = pixies.firstIndex(where: { $0.id == target })
        else { return }
        var order = pixies.map(\.id)
        order.insert(order.remove(at: from), at: to)
        try await reorder(order)
    }

    /// Move Up (-1) and Move Down (1) among the pixies the list shows.
    public func move(_ id: String, by offset: Int, among listed: [String]) async throws {
        guard let index = listed.firstIndex(of: id), listed.indices.contains(index + offset)
        else { return }
        try await move(id, onto: listed[index + offset])
    }

    /// Shows the order at once and saves it after the earlier reorders. Once the last one
    /// answers, the list shows the order the daemon holds: a refused one goes back, and a
    /// refused one under a newer saved one shows the newer one.
    private func reorder(_ ids: [String]) async throws {
        if unordered == 0 {
            confirmedOrder = pixies.map(\.id)
        }
        pixies = Self.placed(pixies, in: ids)
        unordered += 1
        let previous = reorders
        let call = Task {
            _ = try? await previous?.value
            return try await api.reorderPixies(ids)
        }
        reorders = call
        defer { settleOrder(call) }
        let answer = try await call.value
        confirmedOrder = answer.map(\.id)
        for pixie in answer {
            receive(pixie)
        }
    }

    private func settleOrder(_ call: Task<[Pixie], any Error>) {
        if reorders == call {
            reorders = nil
        }
        unordered -= 1
        if unordered == 0 {
            pixies = Self.placed(pixies, in: confirmedOrder)
        }
    }

    public func delete(_ id: String) async throws {
        try await api.deletePixie(id)
        pixies.removeAll { $0.id == id }
    }

    /// The pixie's chat after the message; the caller keeps it in the sessions store.
    /// The chat comes with the queued message when it was busy.
    public func send(_ id: String, text: String) async throws -> SentMessage {
        try await api.sendToPixie(id, text: text)
    }

    public func reset(_ id: String) async throws {
        store(try await api.resetPixie(id))
    }

    public func file(_ id: String, name: String) async throws -> PixieFile {
        try await api.pixieFile(id, name: name)
    }

    /// Fails with `APIError.staleFile` when the file changed since `hash` was read.
    public func save(_ id: String, name: String, text: String, hash: String?) async throws
        -> PixieFile
    {
        try await api.savePixieFile(id, name: name, text: text, hash: hash)
    }

    public func notes(_ id: String) async throws -> [String] {
        try await api.pixieNotes(id)
    }

    public func search(_ id: String, query: String) async throws -> [PixieSearchHit] {
        try await api.searchPixie(id, query: query)
    }

    /// A pixie from the daemon: kept aside while its saves run, ignored when older than
    /// the one shown.
    private func receive(_ pixie: Pixie) {
        if unsaved[pixie.id] != nil {
            confirmed[pixie.id] = Self.newest(confirmed[pixie.id], pixie)
            return
        }
        if let shown = pixies.first(where: { $0.id == pixie.id }),
            shown.updatedAt > pixie.updatedAt
        {
            return
        }
        store(pixie)
    }

    /// After a save answers: once it was the last, the daemon's pixie shows.
    private func settle(_ id: String, _ save: Task<Pixie, any Error>) {
        if saves[id] == save {
            saves[id] = nil
        }
        guard let count = unsaved[id] else { return }
        let left = count - 1
        unsaved[id] = left > 0 ? left : nil
        guard left <= 0, let latest = confirmed.removeValue(forKey: id) else { return }
        if pixies.contains(where: { $0.id == id }) {
            store(latest)
        }
    }

    private static func newest(_ kept: Pixie?, _ pixie: Pixie) -> Pixie {
        guard let kept, kept.updatedAt > pixie.updatedAt else { return pixie }
        return kept
    }

    /// The pixies in the order the ids give, then any the ids leave out (created
    /// meanwhile), positions 0 up. Ids of pixies gone meanwhile are skipped.
    private static func placed(_ list: [Pixie], in ids: [String]) -> [Pixie] {
        let byID = Dictionary(uniqueKeysWithValues: list.map { ($0.id, $0) })
        let named = Set(ids)
        let ordered = ids.compactMap { byID[$0] } + list.filter { !named.contains($0.id) }
        return ordered.enumerated().map { index, pixie in
            var pixie = pixie
            pixie.position = index
            return pixie
        }
    }

    @discardableResult
    private func store(_ pixie: Pixie) -> Pixie {
        var list = pixies.filter { $0.id != pixie.id }
        list.append(pixie)
        pixies = Self.sorted(list)
        return pixie
    }

    private static func sorted(_ list: [Pixie]) -> [Pixie] {
        list.sorted { ($0.position, $0.id) < ($1.position, $1.id) }
    }
}
