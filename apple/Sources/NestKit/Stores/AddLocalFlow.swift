import Foundation
import Observation

/// The Add local model sheet (B106): Find on this Mac lists the running servers' models
/// (those good at tools chosen) and the downloaded ones; Enter address checks a server,
/// with an optional key. Add sends each server's chosen models.
@MainActor @Observable
public final class AddLocalFlow {
    public enum Tab: Hashable, Sendable {
        case find, address
    }

    public var tab: Tab
    public private(set) var found: LocalFind?
    public private(set) var finding = false
    public var address = ""
    public var key = ""
    public private(set) var check: LocalCheck?
    /// The address the check was made for, as sent.
    public private(set) var checkedAddress: String?
    public private(set) var checking = false
    public private(set) var adding = false
    /// Chosen models, by `FoundModel.id`.
    private var selected: Set<String> = []

    public let store: LocalModelsStore

    public init(store: LocalModelsStore, tab: Tab = .find) {
        self.store = store
        self.tab = tab
    }

    /// Looks again: what runs now and what waits in the model folders.
    public func find() async throws {
        finding = true
        defer { finding = false }
        let found = try await store.api.findLocalModels()
        self.found = found
        choose(found.running) { $0.tools == .good }
    }

    public var canCheck: Bool { !trimmedAddress.isEmpty && !checking }

    /// Checks the typed address with the key, when one was typed; the server's models are
    /// chosen unless weak at tools.
    public func checkAddress() async throws {
        let address = trimmedAddress
        checking = true
        defer { checking = false }
        let check = try await store.api.checkLocalServer(address: address, key: typedKey)
        self.check = check
        checkedAddress = address
        choose(check.models) { $0.tools == .good || $0.tools == .unknown }
    }

    /// The line under Check, once checked.
    public var checkLine: LocalModelText.CheckLine? {
        guard let check, let checkedAddress else { return nil }
        return LocalModelText.checked(check, address: checkedAddress)
    }

    /// The models the tab offers.
    public var choices: [FoundModel] {
        switch tab {
        case .find: found?.running ?? []
        case .address: check.flatMap { $0.ok ? $0.models : nil } ?? []
        }
    }

    /// Added ones show checked.
    public func isSelected(_ model: FoundModel) -> Bool {
        model.added || selected.contains(model.id)
    }

    public func canToggle(_ model: FoundModel) -> Bool {
        !model.added
    }

    public func toggle(_ model: FoundModel) {
        guard canToggle(model) else { return }
        if !selected.insert(model.id).inserted {
            selected.remove(model.id)
        }
    }

    private var chosen: [FoundModel] {
        choices.filter { !$0.added && selected.contains($0.id) }
    }

    public var addTitle: String { LocalModelText.add(count: chosen.count) }

    public var canAdd: Bool { !chosen.isEmpty && !adding }

    /// Adds each server's chosen models, servers in the order listed; the key goes only with
    /// an address entered.
    public func add() async throws {
        adding = true
        defer { adding = false }
        let key = tab == .address ? typedKey : nil
        var addresses: [String] = []
        for model in chosen where !addresses.contains(model.address) {
            addresses.append(model.address)
        }
        let chosen = chosen
        for address in addresses {
            try await store.add(
                address: address, key: key,
                models: chosen.filter { $0.address == address }.map(\.model))
        }
    }

    /// Starts the app's server, then looks again.
    public func start(_ app: LocalApp) async throws {
        try await store.start(app)
        try await find()
    }

    private func choose(_ models: [FoundModel], _ good: (FoundModel) -> Bool) {
        // A model too big for this Mac's memory is left to the user to choose.
        selected.formUnion(
            models.filter { !$0.added && $0.memoryWarning == nil && good($0) }.map(\.id))
    }

    private var trimmedAddress: String {
        address.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var typedKey: String? {
        let key = key.trimmingCharacters(in: .whitespacesAndNewlines)
        return key.isEmpty ? nil : key
    }
}
