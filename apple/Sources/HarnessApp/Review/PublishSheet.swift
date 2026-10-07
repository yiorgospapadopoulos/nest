import HarnessKit
import SwiftUI

/// Approving a review: the commit message, push and pull request choices, then each git
/// step's progress; a failed step shows its error output and can be tried again.
struct PublishSheet: View {
    let approvalID: String
    @Environment(Shell.self) private var shell
    @State private var form: PublishForm?

    var body: some View {
        let approval = shell.approval(approvalID)
        SheetFrame(title: title, width: 540) {
            if let approval, let form = Binding($form) {
                content(approval, form)
            } else {
                Text("This review was already resolved.")
                    .font(.ui(TypeSize.small))
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
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(approval.title).font(.ui(TypeSize.body, .semibold)).lineLimit(1)
                Spacer()
                if let review = approval.review {
                    DiffStat(
                        additions: review.additions, deletions: review.deletions,
                        files: review.files)
                }
            }
            .padding(.top, 14)
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
                .font(.ui(TypeSize.caption))
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
                StepList(progress: progress)
            }
            HStack(spacing: 8) {
                Spacer()
                Button("Cancel") { shell.close() }
                    .buttonStyle(.harness(.plain))
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
                .buttonStyle(.harness(.approve))
                .disabled(running || !form.wrappedValue.canSubmit)
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
            .font(.ui(TypeSize.label, .semibold))
            .foregroundStyle(Palette.t2)
            .padding(.top, 12)
            .padding(.bottom, 5)
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
            .font(.ui(TypeSize.body))
            .focused($focused)
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(Palette.glassClear, in: RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(
                        focused ? accent.accent : Palette.hair, lineWidth: focused ? 2 : 1)
            )
    }
}

/// Commit, push and pull request with their state; a failed step shows git's output.
private struct StepList: View {
    let progress: PublishProgress

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(progress.steps) { step in
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        mark(step.state).frame(width: 16, height: 16)
                        Text(step.kind.title).font(.ui(TypeSize.callout, .semibold))
                        Spacer()
                        Text(label(step.state))
                            .font(.ui(TypeSize.caption))
                            .foregroundStyle(Palette.t3)
                    }
                    if case .failed(let output) = step.state {
                        Text(output)
                            .font(.mono(TypeSize.caption))
                            .foregroundStyle(StatusTone.failed.textColor)
                            .textSelection(.enabled)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                StatusTone.failed.soft, in: RoundedRectangle(cornerRadius: 8))
                    }
                }
            }
            if let failure = progress.failure, progress.failedStep != nil {
                Text(failure.message)
                    .font(.ui(TypeSize.caption))
                    .foregroundStyle(Palette.t3)
                Text(
                    "The review stays open. Fix the cause and try again; finished steps are skipped."
                )
                .font(.ui(TypeSize.caption))
                .foregroundStyle(Palette.t3)
            }
        }
        .padding(12)
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 12))
        .padding(.top, 14)
    }

    @ViewBuilder private func mark(_ state: PublishStepState) -> some View {
        switch state {
        case .pending:
            Circle().strokeBorder(Palette.t3, lineWidth: 1.5)
        case .running:
            Spinner(size: 16)
        case .done:
            Image(systemName: Icon.check)
                .font(.system(size: 8, weight: .heavy))
                .foregroundStyle(.white)
                .frame(width: 16, height: 16)
                .background(StatusTone.review.color, in: Circle())
        case .failed:
            Image(systemName: Icon.close)
                .font(.system(size: 8, weight: .heavy))
                .foregroundStyle(.white)
                .frame(width: 16, height: 16)
                .background(StatusTone.failed.color, in: Circle())
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
