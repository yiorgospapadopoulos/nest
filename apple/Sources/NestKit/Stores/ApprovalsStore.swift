import Foundation
import Observation

/// The pending approval queue across all projects, with question drafts and diffs.
@MainActor @Observable
public final class ApprovalsStore {
    /// Oldest first, as the daemon lists them.
    public private(set) var pending: [Approval] = []
    /// The diff of each session's pending review, as last read; a reload keeps it on
    /// screen until the new one arrives.
    public private(set) var diffs: [String: SessionDiff] = [:]
    /// Sessions whose diff is being read.
    public private(set) var loadingDiffs: Set<String> = []
    /// The review each session's diff was last read for, while that read is the latest and
    /// it succeeded: Approve waits for it (audit BUG-83, M-5).
    private var loadedReviews: [String: String] = [:]
    /// Counts the reads of each session's diff, so only the latest one is kept.
    @ObservationIgnored private var diffReads: [String: Int] = [:]
    /// Approvals with a resolve, approve or feedback call in flight.
    public private(set) var busy: Set<String> = []
    /// Review comments sent on their own, while that send is in flight (B101).
    public private(set) var sendingComments: Set<String> = []
    /// The latest approve call per session.
    public private(set) var publishing: [String: PublishProgress] = [:]
    /// Chosen labels by approval id and question text; starts with the recommended options.
    private var choices: [String: [String: [String]]] = [:]
    /// Questions whose Other option is chosen, by approval id.
    private var others: [String: Set<String>] = [:]
    /// The text typed under Other, by approval id and question text.
    private var otherAnswers: [String: [String: String]] = [:]
    /// Notes for Keep planning, by approval id.
    private var planNotes: [String: String] = [:]
    /// How the chat goes on after Approve plan, by approval id, when the user chose.
    private var planModes: [String: PermissionMode] = [:]

    let api: any NestAPI
    @ObservationIgnored private let live = LiveEventLog()

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Loads the pending approvals; live approval events that arrive meanwhile apply
    /// again on top, so an approval created during a resync stays.
    public func load() async throws {
        _ = try await live.read {
            try await self.api.approvals(status: .pending, project: nil)
        } store: {
            pending = $0
        } replay: {
            apply($0.body)
        }
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

    /// Picks an option: replaces the choice (and Other), or toggles it when several are
    /// allowed.
    public func select(_ label: String, for approval: Approval, question: Question) {
        var chosen = selection(for: approval, question: question)
        if !question.multiSelect {
            chosen = [label]
            others[approval.id]?.remove(question.question)
        } else if let index = chosen.firstIndex(of: label) {
            chosen.remove(at: index)
        } else {
            chosen.append(label)
        }
        choices[approval.id, default: [:]][question.question] = chosen
    }

    /// Whether the question's last option, Other, is chosen.
    public func isOtherChosen(for approval: Approval, question: Question) -> Bool {
        others[approval.id]?.contains(question.question) == true
    }

    /// Chooses Other: in place of the options when one answer is allowed, else toggled
    /// beside them.
    public func chooseOther(for approval: Approval, question: Question) {
        if !question.multiSelect {
            choices[approval.id, default: [:]][question.question] = []
            others[approval.id, default: []].insert(question.question)
        } else if isOtherChosen(for: approval, question: question) {
            others[approval.id]?.remove(question.question)
        } else {
            others[approval.id, default: []].insert(question.question)
        }
    }

    /// The text typed under Other; it counts only while Other is chosen.
    public func otherAnswer(for approval: Approval, question: Question) -> String {
        otherAnswers[approval.id]?[question.question] ?? ""
    }

    public func answerOther(_ text: String, for approval: Approval, question: Question) {
        otherAnswers[approval.id, default: [:]][question.question] = text
    }

    /// What is sent for a question: the chosen options, then Other's trimmed text.
    public func answer(for approval: Approval, question: Question) -> [String] {
        let chosen = selection(for: approval, question: question)
        let other = otherText(for: approval, question: question)
        return chosen + (other.map { $0.isEmpty ? [] : [$0] } ?? [])
    }

    /// Every question has an answer to send, and no chosen Other is blank.
    public func canSubmitAnswers(_ approval: Approval) -> Bool {
        guard let request = approval.question else { return false }
        return request.questions.allSatisfy { question in
            otherText(for: approval, question: question) != ""
                && !answer(for: approval, question: question).isEmpty
        }
    }

    /// Other's trimmed text while Other is chosen, else nil.
    private func otherText(for approval: Approval, question: Question) -> String? {
        guard isOtherChosen(for: approval, question: question) else { return nil }
        return otherAnswer(for: approval, question: question)
            .trimmingCharacters(in: .whitespacesAndNewlines)
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

    /// How the chat goes on once the plan is approved: Accept edits until the user picks.
    public func planMode(for approval: Approval) -> PermissionMode {
        planModes[approval.id] ?? .acceptEdits
    }

    public func setPlanMode(_ mode: PermissionMode, for approval: Approval) {
        planModes[approval.id] = mode
    }

    /// Continues with the plan; the daemon switches the chat to the chosen mode, which
    /// is returned.
    @discardableResult
    public func approvePlan(_ approval: Approval) async throws -> PermissionMode {
        let mode = planMode(for: approval)
        try await resolve(approval, .approvePlan(mode: mode))
        return mode
    }

    /// Sends Claude back to planning with the typed note, if any.
    public func keepPlanning(_ approval: Approval) async throws {
        try await resolve(approval, .keepPlanning(note: planNote(for: approval)))
    }

    // MARK: Reviews

    /// Reads the review's diff again; the sheets call it each time they open, and a
    /// refused approve calls it too. The diff shown stays until the new one arrives. When
    /// the changes or HEAD differ from the ones shown, "I checked" has to be given again.
    @discardableResult
    public func loadDiff(for approval: Approval) async throws -> SessionDiff {
        let session = approval.sessionID
        let read = (diffReads[session] ?? 0) + 1
        diffReads[session] = read
        loadingDiffs.insert(session)
        loadedReviews[session] = nil
        defer {
            if diffReads[session] == read {
                loadingDiffs.remove(session)
            }
        }
        let diff = try await api.diff(session)
        // A newer read, or the review going away, replaced this one meanwhile.
        guard diffReads[session] == read else { return diff }
        diffs[session] = diff
        loadedReviews[session] = approval.id
        return diff
    }

    /// The review's diff was read for it and no newer read runs: what Approve sends back.
    public func isReviewLoaded(_ approval: Approval) -> Bool {
        loadedReviews[approval.sessionID] == approval.id
            && !loadingDiffs.contains(approval.sessionID)
    }

    /// The approve sheet's starting point for a review of this session.
    public func publishForm(for approval: Approval, session: Session?) -> PublishForm {
        PublishForm(approval: approval, session: session)
    }

    public func progress(session: String) -> PublishProgress? {
        publishing[session]
    }

    /// Commits, and pushes and opens a pull request as the form asks; progress follows
    /// the daemon's git events. A failed step leaves the review pending for a retry. The
    /// HEAD commit and fingerprint of the diff read for this review go along, so the daemon
    /// refuses if either changed since; without that diff nothing is sent.
    @discardableResult
    public func publish(_ approval: Approval, _ form: PublishForm) async throws -> Session {
        guard isReviewLoaded(approval), let diff = diffs[approval.sessionID] else {
            throw APIError.invalidInput("The changes are still loading. Approve once they show.")
        }
        let progress = PublishProgress(steps: form.steps)
        publishing[approval.sessionID] = progress
        progress.start()
        var request = form.request
        request.expectedHead = diff.head?.commit
        request.expectedFingerprint = diff.fingerprint
        do {
            let session = try await track(approval) {
                try await self.api.approve(approval.sessionID, request)
            }
            progress.finish(session)
            remove(approval.id)
            forgetDiff(of: approval.sessionID)
            return session
        } catch {
            progress.finish(error as? APIError ?? .transport(error.localizedDescription))
            throw error
        }
    }

    /// Sends a note back into the session. The review stays pending: a turn that changes
    /// the work replaces it through its events (B56).
    @discardableResult
    public func feedback(_ approval: Approval, text: String) async throws -> Session {
        try await track(approval) { try await self.api.feedback(approval.sessionID, text: text) }
    }

    // MARK: Merges

    /// Merges the approval's pull request; the daemon closes the chat and removes its
    /// worktree. Its branch is deleted on GitHub only with `deleteBranch`. A failed merge
    /// leaves the approval pending.
    @discardableResult
    public func merge(
        _ approval: Approval, method: MergeMethod = .squash, deleteBranch: Bool = false
    ) async throws -> Session {
        let request = MergeRequest(method: method, deleteBranch: deleteBranch)
        let session = try await track(approval) {
            try await self.api.merge(approval.sessionID, request)
        }
        remove(approval.id)
        return session
    }

    // MARK: Review comments (B101)

    /// The daemon sends all pending review comments to the chat and resolves the approval;
    /// a failed send leaves it pending.
    public func sendReviewComments(_ approval: Approval) async throws {
        try await track(approval) {
            try await self.api.reviewFeedback(approval.sessionID, ids: nil)
        }
        remove(approval.id)
    }

    /// Sends one comment; the daemon then supersedes the approval with the rest, or
    /// resolves it when none remain.
    public func sendReviewComment(_ comment: String, of approval: Approval) async throws {
        sendingComments.insert(comment)
        defer { sendingComments.remove(comment) }
        try await api.reviewFeedback(approval.sessionID, ids: [comment])
    }

    // MARK: Events

    /// Approval events, and the git steps of an approve call in flight.
    public func apply(_ event: Event) {
        live.record(event)
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
            // A new review of the chat makes the diff read for the old one stale.
            if approval.kind == .review && loadedReviews[approval.sessionID] != approval.id {
                forgetDiff(of: approval.sessionID)
            }
        case .approvalResolved(let approval):
            remove(approval.id)
            if approval.kind == .review {
                forgetDiff(of: approval.sessionID)
            }
        case .sessionDeleted(let session):
            pending.removeAll { $0.sessionID == session }
            forgetDiff(of: session)
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

    /// Drops the session's diff, and the result of any read still running.
    private func forgetDiff(of session: String) {
        diffs[session] = nil
        loadedReviews[session] = nil
        loadingDiffs.remove(session)
        diffReads[session, default: 0] += 1
    }

    private func remove(_ id: String) {
        pending.removeAll { $0.id == id }
        choices[id] = nil
        others[id] = nil
        otherAnswers[id] = nil
        planNotes[id] = nil
        planModes[id] = nil
    }
}
