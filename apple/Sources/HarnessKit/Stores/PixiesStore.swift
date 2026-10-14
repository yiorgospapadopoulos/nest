import Foundation
import Observation

/// The user's pixies, in the order they set, with the actions of the Pixies section (D072).
@MainActor @Observable
public final class PixiesStore {
    /// Every pixie, hidden ones too, sorted by position.
    public private(set) var pixies: [Pixie] = []

    let api: any HarnessAPI

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
        case .pixieUpdated(let pixie): store(pixie)
        case .pixieDeleted(let id): pixies.removeAll { $0.id == id }
        default: break
        }
    }

    // MARK: Actions

    @discardableResult
    public func create(_ request: CreatePixieRequest) async throws -> Pixie {
        store(try await api.createPixie(request))
    }

    public func update(_ id: String, _ request: UpdatePixieRequest) async throws {
        store(try await api.updatePixie(id, request))
    }

    public func delete(_ id: String) async throws {
        try await api.deletePixie(id)
        pixies.removeAll { $0.id == id }
    }

    /// The pixie's chat after the message; the caller keeps it in the sessions store.
    public func send(_ id: String, text: String) async throws -> Session {
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
