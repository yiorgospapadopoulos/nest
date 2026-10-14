import NestKit
import SwiftUI

/// Approving a review: the commit message, push and pull request choices, then each git
/// step's progress; a failed step shows its error output and can be tried again.
struct PublishSheet: View {
    let approvalID: String
    @Environment(Shell.self) private var shell
    @State private var form: PublishForm?
    @State private var loadFailure: String?

    var body: some View {
        let approval = shell.approval(approvalID)
        let remote = approval.flatMap {
            shell.approvals.progress(session: $0.sessionID)?.failure?.pushRemote
        }
        // A push address to confirm brings Push there into view.
        SheetFrame(
            title: title, width: 540, scrollTarget: remote.map { _ in RemoteConfirmation.id }
        ) {
            if let approval, let form = Binding($form) {
                content(approval, form)
            } else {
                Text("This review was already resolved.")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 20)
            }
        }
        .onAppear {
            if let approval {
                form = shell.approvals.publishForm(
                    for: approval, session: shell.sessions.session(approval.sessionID))
            }
        }
        // A violation found while the sheet is open, as after a refused approve.
        .onChange(of: approval.flatMap { shell.sessions.session($0.sessionID)?.gitViolation }) {
            if let approval {
                form?.follow(shell.sessions.session(approval.sessionID))
            }
        }
        // Approve sends the HEAD and fingerprint of the diff it shows, so it is read again
        // on every opening and Approve waits for it.
        .task(id: approvalID) {
            guard let approval else { return }
            loadFailure = nil
            do {
                try await shell.approvals.loadDiff(for: approval)
            } catch {
                loadFailure = "Could not read the changes: \(Shell.describe(error))"
            }
        }
    }

    private var title: String {
        guard let form else { return "Approve" }
        if form.steps.contains(.pr) {
            return "Approve and open PR"
        }
        return form.push ? "Approve and push" : "Approve and commit"
    }

    @ViewBuilder private func content(_ approval: Approval, _ form: Binding<PublishForm>)
        -> some View
    {
        let progress = shell.approvals.progress(session: approval.sessionID)
        let running = progress?.isRunning ?? false
        let loaded = shell.approvals.isReviewLoaded(approval)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(approval.title).font(.ui(TypeSize.ui, .medium)).lineLimit(1)
                Spacer()
                if let review = approval.review {
                    DiffStat(
                        additions: review.additions, deletions: review.deletions,
                        files: review.files)
                }
            }
            .padding(.top, 14)
            if let diff = shell.approvals.diffs[approval.sessionID] {
                PublishTarget(diff: diff).padding(.top, 10)
            }
            if let loadFailure {
                Text(loadFailure)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            } else if !loaded {
                HStack(spacing: 8) {
                    Spinner()
                    Text("Reading the changes…")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
                .padding(.top, 8)
            }
            if form.wrappedValue.hasViolation {
                ViolationNotice(approval: approval)
                    .onChange(of: shell.approvals.acknowledgedViolations) { _, acknowledged in
                        form.wrappedValue.acknowledgeViolation = acknowledged.contains(approval.id)
                    }
            }
            FieldLabel(text: "Commit message")
            SheetTextField(placeholder: "Commit message", text: form.commitMessage, lines: 3)
            SheetRow(label: "Push the branch") {
                Switch(isOn: form.wrappedValue.push) { form.wrappedValue.push.toggle() }
                    .accessibilityLabel("Push the branch")
            }
            .padding(.top, 8)
            SheetRow(label: "Open a pull request") {
                Switch(isOn: form.wrappedValue.openPR && form.wrappedValue.canOpenPR) {
                    form.wrappedValue.openPR.toggle()
                }
                .disabled(!form.wrappedValue.canOpenPR)
                .opacity(form.wrappedValue.canOpenPR ? 1 : 0.4)
                .accessibilityLabel("Open a pull request")
            }
            if form.wrappedValue.mode == .inPlace {
                Text(
                    "This chat works in the project folder, so its files are committed on the current branch without a pull request."
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .fixedSize(horizontal: false, vertical: true)
            }
            if form.wrappedValue.steps.contains(.pr) {
                FieldLabel(text: "Pull request title (optional)")
                SheetTextField(
                    placeholder: form.wrappedValue.commitMessage, text: form.prTitle, lines: 1)
                FieldLabel(text: "Pull request description (optional)")
                SheetTextField(placeholder: "Optional", text: form.prBody, lines: 3)
            }
            if let progress {
                StepList(progress: progress) { url in
                    shell.pushThere(approval, form.wrappedValue, url: url)
                }
            }
            HStack(spacing: 6) {
                Spacer()
                Button("Cancel") { shell.close() }
                    .buttonStyle(.nest(.soft))
                Button {
                    shell.publish(approval, form.wrappedValue)
                } label: {
                    if running {
                        Label("Publishing…", systemImage: Icon.pullRequest)
                    } else {
                        Label(
                            progress?.failure == nil ? title : "Try again",
                            systemImage: Icon.pullRequest)
                    }
                }
                .buttonStyle(.nest(.primary))
                .disabled(running || !loaded || !form.wrappedValue.canSubmit)
                .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 16)
        }
        .disabled(running)
    }
}

private struct FieldLabel: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.top, 12)
            .padding(.bottom, 4)
    }
}

private struct SheetTextField: View {
    let placeholder: String
    @Binding var text: String
    let lines: Int
    @Environment(\.accentColors) private var accent
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $text, axis: .vertical)
            .accessibilityLabel(placeholder)
            .overlay(alignment: .topLeading) { Placeholder(text: placeholder, shown: text.isEmpty) }
            .lineLimit(lines...max(lines, 6))
            .textFieldStyle(.plain)
            .font(.ui(TypeSize.ui))
            .focused($focused)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(Palette.soft, in: .rounded(Radius.row))
            .overlay(
                RoundedRectangle.rounded(Radius.row)
                    .strokeBorder(focused ? accent.focus : .clear, lineWidth: 1)
            )
    }
}

/// Commit, push and pull request with their state; a failed step shows git's output.
private struct StepList: View {
    let progress: PublishProgress
    /// Approves again, pushing to the address origin pushes to now.
    let pushThere: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(progress.steps) { step in
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        mark(step.state).frame(width: 12, height: 12)
                        Text(step.kind.title).font(.ui(TypeSize.ui))
                        Spacer()
                        Text(label(step.state))
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    if case .failed(let output) = step.state {
                        Text(output)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(StatusTone.failed.color)
                            .textSelection(.enabled)
                            .padding(.leading, 20)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            if let failure = progress.failure, progress.failedStep != nil {
                Text(failure.message)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                Text(
                    "The review stays open. Fix the cause and try again; finished steps are skipped."
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            } else if let failure = progress.failure {
                // Refused before any step ran: the daemon's reason, and what to do.
                Text(failure.message)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(StatusTone.failed.color)
                    .fixedSize(horizontal: false, vertical: true)
                if case .approveRefused(_, let reason, _) = failure, let hint = reason.hint {
                    Text(hint)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
                if let remote = failure.pushRemote {
                    RemoteConfirmation(remote: remote, push: pushThere)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .softFill()
        .padding(.top, 14)
    }

    @ViewBuilder private func mark(_ state: PublishStepState) -> some View {
        switch state {
        case .pending:
            Circle().strokeBorder(Palette.t3, lineWidth: 1).frame(width: 8, height: 8)
        case .running:
            Spinner(size: 10, lineWidth: 1.5)
        case .done:
            Image(systemName: Icon.check)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(StatusTone.review.color)
        case .failed:
            Image(systemName: Icon.close)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(StatusTone.failed.color)
        }
    }

    private func label(_ state: PublishStepState) -> String {
        switch state {
        case .pending: "Waiting"
        case .running: "Running"
        case .done: "Done"
        case .failed: "Failed"
        }
    }
}

/// Where origin pushes now, after approving was refused for it, and Push there (I-008).
private struct RemoteConfirmation: View {
    static let id = "push-remote"

    let remote: PushRemote
    let push: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(remote.summary)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            ForEach(remote.urls, id: \.self) { url in
                Text(url)
                    .font(.mono(TypeSize.meta, .medium))
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            if let previous = remote.confirmedURL {
                Text("Confirmed before: \(previous)")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            if let target = remote.target {
                Button {
                    push(target)
                } label: {
                    Label("Push there", systemImage: Icon.send)
                }
                .buttonStyle(.nest(.primary))
                .fixedSize()
                .help("Approve again and remember this address for the project")
            }
        }
        .padding(.top, 4)
        .id(Self.id)
    }
}
