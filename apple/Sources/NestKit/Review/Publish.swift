import Foundation
import Observation

/// A step of approving a review, named as the daemon names them in `git.failed`.
public enum PublishStepKind: String, Sendable, CaseIterable {
    case commit, push, pr

    public var title: String {
        switch self {
        case .commit: "Commit"
        case .push: "Push"
        case .pr: "Open pull request"
        }
    }
}

/// A review rejected before reviews lost Reject (B56) only resolved the review; its
/// transcript line says the changes stayed (B54).
public enum RejectConsequence {
    /// The transcript's line for a rejected review.
    public static let transcript = "Rejected. Changes kept, nothing committed"
}

/// What the approve sheet edits: the commit message and whether to open a pull request.
/// Approve pushes only to open a pull request,
/// for a worktree chat that has none yet; otherwise it commits and never pushes (B56).
public struct PublishForm: Sendable, Hashable {
    public var commitMessage: String
    public var openPR = true
    public var prTitle = ""
    public var prBody = ""
    /// The push address the user confirmed after approving was refused for it (I-008).
    public var confirmRemoteURL: String?
    public let mode: SessionMode
    /// The chat's pull request is already open.
    public let hasPullRequest: Bool
    /// In-place sessions commit only the reviewed files.
    public let files: [String]

    /// Starts from the session's title as the commit message.
    public init(approval: Approval, session: Session?) {
        commitMessage = approval.title
        mode = session?.mode ?? .worktree
        hasPullRequest = session?.prURL != nil
        files = approval.review?.paths ?? []
    }

    /// Whether the chat's Approve pushes: only a worktree chat without a pull request,
    /// to open one.
    public static func pushes(for session: Session?) -> Bool {
        session?.mode != .inPlace && session?.prURL == nil
    }

    /// The Approve button outside the sheet, on the review card and the changes sheet.
    public static func approveTitle(for session: Session?) -> String {
        pushes(for: session) ? "Approve and open PR" : "Approve and commit"
    }

    /// In-place sessions work on the checkout's own branch, and a chat with a pull request
    /// already has one, so neither opens one.
    public var canOpenPR: Bool { mode != .inPlace && !hasPullRequest }

    /// Approve pushes the branch, to open the pull request.
    public var pushes: Bool { canOpenPR && openPR }

    /// The sheet's title and Approve button.
    public var title: String { pushes ? "Approve and open PR" : "Approve and commit" }

    /// Why the sheet offers no pull request, when it offers none.
    public var note: String? {
        if mode == .inPlace {
            return
                "This chat works in the project folder, so its files are committed on the current branch, without pushing or a pull request."
        }
        if hasPullRequest {
            return
                "This chat's pull request is already open. Approve commits to its branch without pushing; push it yourself to update the pull request."
        }
        return nil
    }

    /// The toast once approving went through.
    public func done(_ title: String) -> String {
        pushes ? "Opened a pull request for \(title)" : "Committed \(title) without pushing"
    }

    public var canSubmit: Bool {
        !commitMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// The steps the daemon will run, in order.
    public var steps: [PublishStepKind] {
        pushes ? [.commit, .push, .pr] : [.commit]
    }

    public var request: ApproveRequest {
        func optional(_ text: String) -> String? {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        return ApproveRequest(
            commitMessage: commitMessage.trimmingCharacters(in: .whitespacesAndNewlines),
            files: mode == .inPlace ? files : nil, push: pushes, openPR: pushes,
            prTitle: pushes ? optional(prTitle) : nil,
            prBody: pushes ? optional(prBody) : nil,
            confirmRemoteURL: pushes ? confirmRemoteURL : nil)
    }
}

public enum PublishStepState: Sendable, Hashable {
    case pending, running, done
    /// The step's error output, or the failure's message.
    case failed(String)
}

public struct PublishStep: Sendable, Hashable, Identifiable {
    public let kind: PublishStepKind
    public var state: PublishStepState

    public var id: PublishStepKind { kind }
}

/// The progress of one approve call, step by step, from the daemon's git events.
@MainActor @Observable
public final class PublishProgress {
    public private(set) var steps: [PublishStep]
    public private(set) var isRunning = false
    /// Set when the call failed; the review stays pending and can be approved again.
    public private(set) var failure: APIError?
    /// The session as the successful call returned it.
    public private(set) var result: Session?

    public init(steps: [PublishStepKind]) {
        self.steps = steps.map { PublishStep(kind: $0, state: .pending) }
    }

    public var failedStep: PublishStep? {
        steps.first { if case .failed = $0.state { true } else { false } }
    }

    func start() {
        isRunning = true
        failure = nil
        result = nil
        steps = steps.map { PublishStep(kind: $0.kind, state: .pending) }
        markRunning(from: 0)
    }

    /// A step's event: it and every step before it are done, and the next one runs.
    func complete(_ kind: PublishStepKind) {
        guard let index = steps.firstIndex(where: { $0.kind == kind }) else { return }
        for earlier in 0...index {
            steps[earlier].state = .done
        }
        markRunning(from: index + 1)
    }

    func fail(step kind: PublishStepKind?, message: String) {
        guard
            let index = kind.flatMap({ kind in steps.firstIndex { $0.kind == kind } })
                ?? steps.firstIndex(where: { $0.state == .running }) ?? steps.indices.first
        else { return }
        // The daemon runs steps in order, so the ones before the failure went through.
        for earlier in steps.indices where earlier < index {
            steps[earlier].state = .done
        }
        steps[index].state = .failed(message)
        for later in steps.indices where later > index {
            steps[later].state = .pending
        }
    }

    func finish(_ session: Session) {
        steps = steps.map { PublishStep(kind: $0.kind, state: .done) }
        result = session
        isRunning = false
    }

    /// A refusal (409) ran no step: the steps stay pending and the failure says why.
    func finish(_ error: APIError) {
        if error.isConflict {
            steps = steps.map { PublishStep(kind: $0.kind, state: .pending) }
        } else if case .gitFailed(_, let step, let stderr) = error {
            let message = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            fail(
                step: PublishStepKind(rawValue: step),
                message: message.isEmpty ? error.message : message)
        } else if failedStep == nil {
            fail(step: nil, message: error.message)
        }
        failure = error
        isRunning = false
    }

    private func markRunning(from index: Int) {
        if steps.indices.contains(index) {
            steps[index].state = .running
        }
    }
}
