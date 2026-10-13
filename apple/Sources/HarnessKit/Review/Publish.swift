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

/// What rejecting a review does to the chat's changes, for its confirmation: an in-place
/// chat has no worktree to remove, so its edits stay in the folder.
public enum RejectConsequence {
    public static func of(_ mode: SessionMode?) -> String {
        mode == .inPlace
            ? "The chat closes. Its changes stay in your folder."
            : "The chat closes and its worktree and branch are removed. Nothing is merged."
    }
}

/// What the approve sheet edits: the commit message, push and pull request choices, and
/// the acknowledgement a git violation needs.
public struct PublishForm: Sendable, Hashable {
    public var commitMessage: String
    public var push = true
    public var openPR = true
    public var prTitle = ""
    public var prBody = ""
    public var acknowledgeViolation: Bool
    /// The push address the user confirmed after approving was refused for it (I-008).
    public var confirmRemoteURL: String?
    /// The agent changed git refs itself; publishing needs an explicit acknowledgement.
    public private(set) var hasViolation: Bool
    public let mode: SessionMode
    /// In-place sessions commit only the reviewed files.
    public let files: [String]

    /// Starts from the session's title as the commit message.
    public init(approval: Approval, session: Session?, acknowledged: Bool = false) {
        commitMessage = approval.title
        hasViolation = session?.gitViolation ?? false
        acknowledgeViolation = acknowledged
        mode = session?.mode ?? .worktree
        files = approval.review?.paths ?? []
    }

    /// Takes up a violation found while the form is open, as the session now reads.
    public mutating func follow(_ session: Session?) {
        hasViolation = session?.gitViolation ?? false
    }

    /// In-place sessions work on the checkout's own branch, so no pull request is opened.
    public var canOpenPR: Bool { mode != .inPlace && push }

    public var canSubmit: Bool {
        !commitMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (!hasViolation || acknowledgeViolation)
    }

    /// The steps the daemon will run, in order.
    public var steps: [PublishStepKind] {
        guard push else { return [.commit] }
        return canOpenPR && openPR ? [.commit, .push, .pr] : [.commit, .push]
    }

    public var request: ApproveRequest {
        func optional(_ text: String) -> String? {
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }
        let pullRequest = steps.contains(.pr)
        return ApproveRequest(
            commitMessage: commitMessage.trimmingCharacters(in: .whitespacesAndNewlines),
            files: mode == .inPlace ? files : nil, push: push, openPR: pullRequest,
            prTitle: pullRequest ? optional(prTitle) : nil,
            prBody: pullRequest ? optional(prBody) : nil,
            acknowledgeViolation: hasViolation && acknowledgeViolation,
            confirmRemoteURL: push ? confirmRemoteURL : nil)
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
