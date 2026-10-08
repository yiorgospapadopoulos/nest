import AppKit
import HarnessKit
import SwiftUI

/// A pending approval with its actions: a permission prompt, Claude's questions or work
/// to review. The Needs you card shows it on a fill with the chat's name; the transcript
/// shows a compact version on the kind's soft color.
struct ApprovalCard: View {
    enum Style {
        case panel, inline
    }

    let approval: Approval
    let style: Style
    @Environment(Shell.self) private var shell

    var body: some View {
        let green = approval.kind == .review || approval.kind == .merge
        let tone: StatusTone = green ? .review : .waiting
        let busy = shell.approvals.busy.contains(approval.id)
        VStack(alignment: .leading, spacing: 0) {
            header(tone)
            Group {
                switch approval.kind {
                case .question: QuestionBody(approval: approval, style: style)
                case .review: ReviewBody(approval: approval, style: style)
                case .plan: PlanBody(approval: approval, style: style)
                case .merge: MergeBody(approval: approval, style: style)
                case .permission, .unknown: PermissionBody(approval: approval, style: style)
                }
            }
            .disabled(busy)
        }
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            style == .panel ? Palette.fill : tone.soft,
            in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private func header(_ tone: StatusTone) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 11, weight: .semibold))
            Text(title)
            if shell.approvals.busy.contains(approval.id) {
                ProgressView().controlSize(.mini)
            }
            if style == .panel {
                Spacer(minLength: 8)
                ChatLink(chat: approval.sessionID, title: approval.title)
                    .font(.ui(TypeSize.caption, .medium))
                    .foregroundStyle(Palette.t3)
                    .frame(maxWidth: 150, alignment: .trailing)
            }
        }
        .font(.ui(TypeSize.caption, .bold))
        .foregroundStyle(tone.textColor)
    }

    private var icon: String {
        switch approval.kind {
        case .question: Icon.question
        case .review: Icon.check
        case .plan: Icon.plan
        case .merge: Icon.merge
        case .permission, .unknown: Icon.shield
        }
    }

    private var title: String {
        switch (approval.kind, style) {
        case (.question, .panel): "Question"
        case (.question, .inline): "Question from Claude"
        case (.review, _): "Ready for review"
        case (.plan, .panel): "Plan"
        case (.plan, .inline): "Plan ready for review"
        case (.merge, _): "Ready to merge"
        case (_, .panel): "Permission"
        case (_, .inline): "Permission needed"
        }
    }
}

/// The command in mono, Claude's prompt and why it asks, and Approve, Reject, Always allow.
private struct PermissionBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let permission = approval.permission {
                CommandBox(
                    text:
                        "\(permission.tool) \(ToolSummary.argument(tool: permission.tool, input: permission.input))"
                )
                .padding(.vertical, 6)
                if let title = permission.title {
                    Text(title)
                        .font(.ui(TypeSize.label))
                        .foregroundStyle(Palette.t2)
                        .lineSpacing(1.5)
                }
                if let reason = permission.reason {
                    Text(reason)
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(Palette.t3)
                        .lineSpacing(1.5)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 2)
                }
            }
            ActionRow {
                Button {
                    shell.allow(approval)
                } label: {
                    Label("Approve", systemImage: Icon.check).grows(style)
                }
                .buttonStyle(.card(.approve))
                Button {
                    shell.deny(approval)
                } label: {
                    Text("Reject").grows(style)
                }
                .buttonStyle(.card(.danger))
                Button("Always allow") { shell.allow(approval, always: true) }
                    .buttonStyle(.card(.ghost))
                    .fixedSize()
                    .help("Allow this tool for the rest of the chat")
            }
        }
    }
}

/// The plan as rendered markdown, an optional note, and Approve plan (the chat continues
/// in Accept edits) or Keep planning (with the note).
private struct PlanBody: View {
    static let panelHeight: CGFloat = 260

    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        let note = Binding(
            get: { shell.approvals.planNote(for: approval) },
            set: { shell.approvals.setPlanNote($0, for: approval) })
        VStack(alignment: .leading, spacing: 0) {
            Group {
                if style == .panel {
                    ScrollView { plan }
                        .frame(maxHeight: Self.panelHeight)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    plan
                }
            }
            .background(glass.subtle, in: glass.rounded(glass.radius.item))
            .overlay(glass.rounded(glass.radius.item).strokeBorder(Palette.hair))
            .padding(.top, 8)
            CardField(placeholder: "Note for Claude (optional)", text: note) {
                shell.keepPlanning(approval)
            }
            .padding(.top, 8)
            ActionRow {
                Button {
                    shell.approvePlan(approval)
                } label: {
                    Label("Approve plan", systemImage: Icon.check).grows(style)
                }
                .buttonStyle(.card(.approve))
                .help("Continue with this plan; the chat switches to Accept edits")
                Button {
                    shell.keepPlanning(approval)
                } label: {
                    Text("Keep planning").grows(style)
                }
                .buttonStyle(.card(.plain))
                .help("Send Claude back to planning, with the note if you wrote one")
            }
        }
    }

    private var plan: some View {
        let text = approval.plan?.plan ?? ""
        return SelectableText(key: text, linkColor: NSColor(accent.accent)) {
            TextStyling.message(RichText.paragraphs(text))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
    }
}

/// The command a permission prompt is about.
struct CommandBox: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.mono(TypeSize.small, .semibold))
            .lineSpacing(2)
            .textSelection(.enabled)
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.codeBackground, in: RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).stroke(Palette.hair))
    }
}

/// Each question with its options as radio rows (the recommended one marked and chosen
/// to start with), a free answer, and Send answer or Dismiss.
private struct QuestionBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell

    var body: some View {
        let questions = approval.question?.questions ?? []
        VStack(alignment: .leading, spacing: 0) {
            ForEach(questions, id: \.question) { question in
                VStack(alignment: .leading, spacing: 0) {
                    Text(question.question)
                        .font(.ui(TypeSize.body, .semibold))
                        .padding(.top, 6)
                        .padding(.bottom, 2)
                    OptionList(approval: approval, question: question)
                    if style == .panel {
                        FreeAnswerField(approval: approval, question: question)
                    }
                }
            }
            ActionRow {
                Button {
                    shell.answer(approval)
                } label: {
                    Text("Send answer").grows(style)
                }
                .buttonStyle(.card(.primary))
                .disabled(!shell.approvals.canSubmitAnswers(approval))
                Button("Dismiss") { shell.dismiss(approval) }
                    .buttonStyle(.card(.ghost))
                    .fixedSize()
                    .help("Let Claude continue without an answer")
            }
        }
    }
}

private struct OptionList: View {
    let approval: Approval
    let question: Question
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        let chosen = shell.approvals.selection(for: approval, question: question)
        let typing = !shell.approvals.freeAnswer(for: approval, question: question)
            .trimmingCharacters(in: .whitespaces).isEmpty
        VStack(spacing: 6) {
            ForEach(question.options, id: \.label) { option in
                let on = chosen.contains(option.label) && !typing
                Button {
                    shell.approvals.answerFreely("", for: approval, question: question)
                    shell.approvals.select(option.label, for: approval, question: question)
                } label: {
                    HStack(alignment: .top, spacing: 8) {
                        mark(on: on, multiple: question.multiSelect)
                        VStack(alignment: .leading, spacing: 1) {
                            HStack(spacing: 6) {
                                Text(option.label).font(.ui(TypeSize.small, .semibold))
                                if option.recommended {
                                    Text("Recommended")
                                        .font(.ui(TypeSize.micro, .bold))
                                        .foregroundStyle(StatusTone.review.textColor)
                                        .padding(.horizontal, 7)
                                        .padding(.vertical, 1)
                                        .background(StatusTone.review.soft, in: Capsule())
                                }
                            }
                            if let description = option.description {
                                Text(description)
                                    .font(.ui(TypeSize.caption))
                                    .foregroundStyle(Palette.t2)
                                    .multilineTextAlignment(.leading)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(Palette.t1)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 7)
                    .background(
                        on ? accent.soft : glass.subtle, in: glass.rounded(glass.radius.item)
                    )
                    .overlay(
                        glass.rounded(glass.radius.item)
                            .strokeBorder(on ? accent.accent : Palette.hair)
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(.top, 6)
    }

    @ViewBuilder private func mark(on: Bool, multiple: Bool) -> some View {
        RoundedRectangle(cornerRadius: multiple ? 4 : 7, style: .continuous)
            .strokeBorder(on ? accent.accent : Palette.t3, lineWidth: on ? 4 : 1.5)
            .frame(width: 14, height: 14)
            .padding(.top, 1)
    }
}

/// The user's own answer; typing replaces the options.
private struct FreeAnswerField: View {
    let approval: Approval
    let question: Question
    @Environment(Shell.self) private var shell

    var body: some View {
        let binding = Binding(
            get: { shell.approvals.freeAnswer(for: approval, question: question) },
            set: { shell.approvals.answerFreely($0, for: approval, question: question) })
        CardField(placeholder: "Your own answer", text: binding)
            .padding(.top, 8)
    }
}

/// Stats, summary and files of the work, the git violation warning, a feedback field,
/// and Approve and open PR, Reject (confirmed), Send feedback.
private struct ReviewBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell
    @State private var feedback = ""
    @State private var confirmingReject = false

    var body: some View {
        let review = approval.review
        let session = shell.sessions.session(approval.sessionID)
        let violation = session?.gitViolation ?? false
        let acknowledged = shell.approvals.acknowledgedViolations.contains(approval.id)
        let git = shell.app.repo(approval.repo)?.git != false
        VStack(alignment: .leading, spacing: 0) {
            if style == .panel {
                Text(approval.title)
                    .font(.ui(TypeSize.body, .semibold))
                    .padding(.top, 6)
            }
            HStack(spacing: 8) {
                if let review {
                    DiffStat(
                        additions: review.additions, deletions: review.deletions,
                        files: review.files)
                    DiffBar(additions: review.additions, deletions: review.deletions)
                }
                Spacer(minLength: 4)
                if git {
                    Button("View changes") { shell.show(.diff(approval.id)) }
                        .buttonStyle(LinkButtonStyle())
                }
            }
            .padding(.top, 6)
            .padding(.bottom, 4)
            if style == .panel {
                if let summary = review?.summary {
                    Text(summary)
                        .font(.ui(TypeSize.label))
                        .foregroundStyle(Palette.t2)
                        .lineSpacing(1.5)
                        .fixedSize(horizontal: false, vertical: true)
                }
                FileList(
                    paths: review?.paths ?? [], diff: shell.approvals.diffs[approval.sessionID])
            }
            if violation {
                ViolationNotice(approval: approval)
            }
            if style == .panel {
                HStack(spacing: 6) {
                    CardField(placeholder: "Feedback for Claude", text: $feedback) {
                        shell.sendFeedback(approval, text: feedback)
                    }
                    Button("Send") { shell.sendFeedback(approval, text: feedback) }
                        .buttonStyle(.card(.plain))
                        .fixedSize()
                        .disabled(feedback.trimmingCharacters(in: .whitespaces).isEmpty)
                        .help("Send feedback to the chat")
                }
                .padding(.top, 8)
            }
            if confirmingReject {
                RejectConfirmation(mode: session?.mode) {
                    confirmingReject = false
                    shell.reject(approval)
                } cancel: {
                    confirmingReject = false
                }
            } else {
                ActionRow {
                    Button {
                        shell.show(.publish(approval.id))
                    } label: {
                        Label(
                            session?.mode == .inPlace
                                ? "Approve and commit" : "Approve and open PR",
                            systemImage: Icon.pullRequest
                        )
                        .grows(style)
                    }
                    .buttonStyle(.card(.approve))
                    .disabled(!git || (violation && !acknowledged))
                    .help(git ? "" : "Not a git repository: nothing to commit")
                    Button("Reject") {
                        withAnimation(.smooth(duration: 0.2)) { confirmingReject = true }
                    }
                    .buttonStyle(.card(.danger))
                }
            }
        }
    }
}

/// The agent changed git refs itself; publishing needs the user to say they checked.
struct ViolationNotice: View {
    let approval: Approval
    @Environment(Shell.self) private var shell

    var body: some View {
        let binding = Binding(
            get: { shell.approvals.acknowledgedViolations.contains(approval.id) },
            set: { on in
                if on {
                    shell.approvals.acknowledgedViolations.insert(approval.id)
                } else {
                    shell.approvals.acknowledgedViolations.remove(approval.id)
                }
            })
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: Icon.warning).font(.system(size: 11, weight: .semibold))
                Text(
                    "The agent ran git itself and changed this chat's branch. Check its commits before publishing."
                )
                .fixedSize(horizontal: false, vertical: true)
            }
            .font(.ui(TypeSize.label, .medium))
            .foregroundStyle(StatusTone.failed.textColor)
            Toggle("I checked, publish anyway", isOn: binding)
                .toggleStyle(SwitchRowStyle())
                .font(.ui(TypeSize.label))
        }
        .padding(9)
        .background(StatusTone.failed.soft, in: RoundedRectangle(cornerRadius: 10))
        .padding(.top, 8)
    }
}

/// The reviewed paths, with their line counts once the diff is loaded.
private struct FileList: View {
    static let shown = 3

    let paths: [String]
    let diff: SessionDiff?

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(paths.prefix(Self.shown), id: \.self) { path in
                let file = diff?.files.first { $0.path == path }
                HStack(spacing: 7) {
                    Image(systemName: Icon.file).font(.system(size: 10)).foregroundStyle(Palette.t3)
                    Text(path)
                        .font(.mono(10.5))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let file {
                        HStack(spacing: 3) {
                            Text("+\(file.additions)").foregroundStyle(Palette.addedText)
                            Text("-\(file.deletions)").foregroundStyle(Palette.removedText)
                        }
                        .font(.mono(10.5, .semibold))
                    }
                }
            }
            if paths.count > Self.shown {
                Text("and \(paths.count - Self.shown) more files")
                    .font(.ui(TypeSize.caption))
                    .foregroundStyle(Palette.t3)
            }
        }
        .padding(.top, 8)
    }
}

/// "Reject this work?" with the consequence and the two choices.
struct RejectConfirmation: View {
    let mode: SessionMode?
    let reject: () -> Void
    let cancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Reject this work?").font(.ui(TypeSize.body, .semibold))
            Text(RejectConsequence.of(mode))
                .font(.ui(TypeSize.label))
                .foregroundStyle(Palette.t2)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Button(action: reject) { Text("Reject").frame(maxWidth: .infinity) }
                    .buttonStyle(.card(.destructive))
                Button(action: cancel) { Text("Cancel").frame(maxWidth: .infinity) }
                    .buttonStyle(.card(.plain))
            }
            .padding(.top, 5)
        }
        .padding(.top, 9)
        .transition(.opacity)
    }
}

/// The five-square bar of additions against deletions.
struct DiffBar: View {
    let additions: Int
    let deletions: Int

    var body: some View {
        let total = max(additions + deletions, 1)
        let green = Int((Double(additions) / Double(total) * 5).rounded())
        HStack(spacing: 1.5) {
            ForEach(0..<5, id: \.self) { index in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(index < green ? StatusTone.review.color : StatusTone.failed.color)
                    .frame(width: 6, height: 6)
            }
        }
        .accessibilityHidden(true)
    }
}

/// The card's button row; in a narrow pane the buttons stack instead of spilling out.
struct ActionRow<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 6) { content() }
            VStack(alignment: .leading, spacing: 6) { content() }
        }
        .padding(.top, 9)
    }
}

/// A one-line field on the card; Return submits when a handler is given.
struct CardField: View {
    let placeholder: String
    @Binding var text: String
    var submit: (() -> Void)?
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $text)
            .accessibilityLabel(placeholder)
            .overlay(alignment: .leading) { Placeholder(text: placeholder, shown: text.isEmpty) }
            .textFieldStyle(.plain)
            .font(.ui(TypeSize.small))
            .focused($focused)
            .onSubmit { submit?() }
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
            .background(glass.subtle, in: glass.rounded(glass.radius.small + 2))
            .overlay(
                glass.rounded(glass.radius.small + 2)
                    .strokeBorder(
                        focused ? accent.accent : Palette.hair, lineWidth: focused ? 2 : 1)
            )
    }
}

/// A field's hint in the tertiary color while it is empty.
struct Placeholder: View {
    let text: String
    let shown: Bool

    var body: some View {
        if shown {
            Text(text)
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

/// Underlined accent text, such as "View changes".
struct LinkButtonStyle: ButtonStyle {
    @Environment(\.accentColors) private var accent

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .font(.ui(TypeSize.small))
                .foregroundStyle(accent.accent)
                .underline()
                .padding(.horizontal, 4)
                .padding(.vertical, 2)
                .background(hovering ? Palette.fill : .clear, in: RoundedRectangle(cornerRadius: 6))
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// The mockup's green switch, label on the left.
struct SwitchRowStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 12) {
            configuration.label
            Spacer(minLength: 0)
            Switch(isOn: configuration.isOn) { configuration.isOn.toggle() }
        }
    }
}

struct Switch: View {
    let isOn: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            Capsule()
                .fill(isOn ? StatusTone.review.color : Palette.fill2)
                .frame(width: 38, height: 22)
                .overlay(alignment: isOn ? .trailing : .leading) {
                    Circle()
                        .fill(.white)
                        .shadow(color: .black.opacity(0.3), radius: 1.5, y: 1)
                        .frame(width: 18, height: 18)
                        .padding(2)
                }
                .animation(.smooth(duration: 0.2), value: isOn)
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(isOn ? [.isToggle, .isSelected] : .isToggle)
    }
}

extension View {
    /// The Needs you card's main buttons share the row; the transcript's keep their size.
    func grows(_ style: ApprovalCard.Style) -> some View {
        fixedSize().frame(maxWidth: style == .panel ? .infinity : nil)
    }
}

extension ButtonStyle where Self == HarnessButtonStyle {
    /// The card's smaller buttons (26 points, 12 point text).
    static func card(_ kind: HarnessButtonStyle.Kind) -> HarnessButtonStyle {
        HarnessButtonStyle(kind: kind, height: 26, fontSize: TypeSize.small)
    }
}
