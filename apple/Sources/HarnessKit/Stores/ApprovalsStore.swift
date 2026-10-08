import Foundation
import Observation

/// The pending approval queue across all projects, with question drafts and diffs.
@MainActor @Observable
public final class ApprovalsStore {
    /// Oldest first, as the daemon lists them.
    public private(set) var pending: [Approval] = []
    /// Loaded diffs by session id.
    public private(set) var diffs: [String: SessionDiff] = [:]
    /// Approvals with a resolve, approve, reject or feedback call in flight.
    public private(set) var busy: Set<String> = []
    /// Reviews whose git violation the user acknowledged, by approval id.
    public var acknowledgedViolations: Set<String> = []
    /// The latest approve call per session.
    public private(set) var publishing: [String: PublishProgress] = [:]
    /// Chosen labels by approval id and question text; starts with the recommended options.
    private var choices: [String: [String: [String]]] = [:]
    /// The user's own answers by approval id and question text.
    private var freeAnswers: [String: [String: String]] = [:]
    /// Notes for Keep planning, by approval id.
    private var planNotes: [String: String] = [:]

    let api: any HarnessAPI

    public init(api: any HarnessAPI) {
        self.api = api
    }

    public func load() async throws {
        pending = try await api.approvals(status: .pending, project: nil)
    }

    public func pending(repo: String) -> [Approval] {
        pending.filter { $0.repo == repo }
    }

    public func pending(session: String) -> [Approval] {
        pending.filter { $0.sessionID == session }
    }

    public func hasPendingReview(session: String) -> Bool {
        pending.contains { $0.sessionID == session && $0.kind == .review }
    }

    // MARK: Permissions

    public func allow(_ approval: Approval, always: Bool = false) async throws {
        try await resolve(approval, .allow(always: always))
    }

    public func deny(_ approval: Approval, message: String? = nil) async throws {
        try await resolve(approval, .deny(message: message))
    }

    // MARK: Questions

    /// The labels chosen for a question; the recommended ones until the user picks.
    public func selection(for approval: Approval, question: Question) -> [String] {
        if let chosen = choices[approval.id]?[question.question] {
            return chosen
        }
        let recommended = question.options.filter(\.recommended).map(\.label)
        return question.multiSelect ? recommended : Array(recommended.prefix(1))
    }

    /// Picks an option: replaces the choice, or toggles it when several are allowed.
    public func select(_ label: String, for approval: Approval, question: Question) {
        var chosen = selection(for: approval, question: question)
        if !question.multiSelect {
            chosen = [label]
        } else if let index = chosen.firstIndex(of: label) {
            chosen.remove(at: index)
        } else {
            chosen.append(label)
        }
        choices[approval.id, default: [:]][question.question] = chosen
    }

    /// The user's own answer as typed; it replaces the options while it is not blank.
    public func freeAnswer(for approval: Approval, question: Question) -> String {
        freeAnswers[approval.id]?[question.question] ?? ""
    }

    public func answerFreely(_ text: String, for approval: Approval, question: Question) {
        freeAnswers[approval.id, default: [:]][question.question] = text
    }

    /// What is sent for a question: the user's own answer, or the chosen options.
    public func answer(for approval: Approval, question: Question) -> [String] {
        let free = freeAnswer(for: approval, question: question)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return free.isEmpty ? selection(for: approval, question: question) : [free]
    }

    /// Every question has an answer to send.
    public func canSubmitAnswers(_ approval: Approval) -> Bool {
        guard let request = approval.question else { return false }
        return request.questions.allSatisfy { !answer(for: approval, question: $0).isEmpty }
    }

    /// Sends the answer of every question; other kinds are left alone.
    public func submitAnswers(_ approval: Approval) async throws {
        guard let request = approval.question else { return }
        var answers: [String: [String]] = [:]
        for question in request.questions {
            answers[question.question] = answer(for: approval, question: question)
        }
        try await resolve(approval, .answer(answers))
    }

    public func dismiss(_ approval: Approval, message: String? = nil) async throws {
        try await resolve(approval, .dismiss(message: message))
    }

    // MARK: Plans

    /// The note sent with Keep planning, as typed.
    public func planNote(for approval: Approval) -> String {
        planNotes[approval.id] ?? ""
    }

    public func setPlanNote(_ note: String, for approval: Approval) {
        planNotes[approval.id] = note
    }

    /// Continues with the plan; the daemon switches the chat to Accept edits.
    public func approvePlan(_ approval: Approval) async throws {
        try await resolve(approval, .approvePlan)
    }

    /// Sends Claude back to planning with the typed note, if any.
    public func keepPlanning(_ approval: Approval) async throws {
        try await resolve(approval, .keepPlanning(note: planNote(for: approval)))
    }

    // MARK: Reviews

    @discardableResult
    public func loadDiff(session: String) async throws -> SessionDiff {
        let diff = try await api.diff(session)
        diffs[session] = diff
        return diff
    }

    /// The approve sheet's starting point for a review of this session.
    public func publishForm(for approval: Approval, session: Session?) -> PublishForm {
        PublishForm(
            approval: approval, session: session,
            acknowledged: acknowledgedViolations.contains(approval.id))
    }

    public func progress(session: String) -> PublishProgress? {
        publishing[session]
    }

    /// Commits, and pushes and opens a pull request as the form asks; progress follows
    /// the daemon's git events. A failed step leaves the review pending for a retry.
    @discardableResult
    public func publish(_ approval: Approval, _ form: PublishForm) async throws -> Session {
        let progress = PublishProgress(steps: form.steps)
        publishing[approval.sessionID] = progress
        progress.start()
        do {
            let session = try await track(approval) {
                try await self.api.approve(approval.sessionID, form.request)
            }
            progress.finish(session)
            remove(approval.id)
            return session
        } catch {
            progress.finish(error as? APIError ?? .transport(error.localizedDescription))
            throw error
        }
    }

    @discardableResult
    public func reject(_ approval: Approval) async throws -> Session {
        let session = try await track(approval) { try await self.api.reject(approval.sessionID) }
        remove(approval.id)
        return session
    }

    /// Sends a note back into the session; the daemon supersedes the review.
    @discardableResult
    public func feedback(_ approval: Approval, text: String) async throws -> Session {
        let session = try await track(approval) {
            try await self.api.feedback(approval.sessionID, text: text)
        }
        remove(approval.id)
        return session
    }

    // MARK: Merges

    /// Merges the approval's pull request; the daemon closes the chat and removes its
    /// worktree. A failed merge leaves the approval pending.
    @discardableResult
    public func merge(_ approval: Approval, method: MergeMethod = .squash) async throws
        -> Session
    {
        let session = try await track(approval) {
            try await self.api.merge(approval.sessionID, MergeRequest(method: method))
        }
        remove(approval.id)
        return session
    }

    // MARK: Events

    /// Approval events, and the git steps of an approve call in flight.
    public func apply(_ event: Event) {
        apply(event.body)
        guard let session = event.sessionID, let progress = publishing[session] else { return }
        switch event.body {
        case .gitCommitted: progress.complete(.commit)
        case .gitPushed: progress.complete(.push)
        case .prOpened: progress.complete(.pr)
        case .gitFailed(let step, let stderr):
            progress.fail(step: PublishStepKind(rawValue: step), message: stderr)
        default: break
        }
    }

    public func apply(_ body: EventBody) {
        switch body {
        case .approvalCreated(let approval) where approval.status == .pending:
            remove(approval.id)
            pending.append(approval)
        case .approvalResolved(let approval):
            remove(approval.id)
        case .sessionDeleted(let session):
            pending.removeAll { $0.sessionID == session }
            diffs[session] = nil
            publishing[session] = nil
        default:
            break
        }
    }

    private func resolve(_ approval: Approval, _ request: ResolveApprovalRequest) async throws {
        _ = try await track(approval) { try await self.api.resolveApproval(approval.id, request) }
        remove(approval.id)
    }

    /// Marks the approval busy while the call runs.
    private func track<T>(_ approval: Approval, _ call: () async throws -> T) async throws -> T {
        busy.insert(approval.id)
        defer { busy.remove(approval.id) }
        return try await call()
    }

    private func remove(_ id: String) {
        pending.removeAll { $0.id == id }
        choices[id] = nil
        freeAnswers[id] = nil
        planNotes[id] = nil
        acknowledgedViolations.remove(id)
    }
}
