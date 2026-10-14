/// The composers' drafts by pane id. A new chat's draft moves to the chat it became, so
/// what is typed or attached while the chat is created stays with it (audit BUG-70).
@MainActor
public final class DraftBook<Draft: AnyObject> {
    private var drafts: [String: Draft] = [:]
    private let make: () -> Draft

    public init(_ make: @escaping () -> Draft) {
        self.make = make
    }

    /// The pane's draft, created empty the first time.
    public func draft(for id: String) -> Draft {
        if let draft = drafts[id] {
            return draft
        }
        let draft = make()
        drafts[id] = draft
        return draft
    }

    /// The pane's draft; `prepare` runs once, when it is created.
    public func draft(for id: String, prepare: (Draft) -> Void) -> Draft {
        if let draft = drafts[id] {
            return draft
        }
        let draft = draft(for: id)
        prepare(draft)
        return draft
    }

    public func remove(_ id: String) {
        drafts[id] = nil
    }

    /// The draft of `id` becomes `newID`'s, replacing any it had.
    public func move(_ id: String, to newID: String) {
        guard let draft = drafts.removeValue(forKey: id) else { return }
        drafts[newID] = draft
    }
}
