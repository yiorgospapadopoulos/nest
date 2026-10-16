import AppKit
import NestKit
import SwiftUI

/// A pending approval with its actions: a permission prompt, Claude's questions or work
/// to review, on a soft fill. The transcript's compact version has a quiet coloured label;
/// the Needs you card shows it without one, under its row that names the chat (B77).
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
            if style == .inline {
                label(tone)
            }
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
        .padding(.horizontal, style == .panel ? 12 : 13)
        .padding(.vertical, style == .panel ? 10 : 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
    }

    private func label(_ tone: StatusTone) -> some View {
        HStack(spacing: 6) {
            StatusDot(tone: tone)
            Text(title)
            if shell.approvals.busy.contains(approval.id) {
                ProgressView().controlSize(.mini)
            }
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(tone.color)
    }

    private var title: String {
        switch approval.kind {
        case .question: "Question from Claude"
        case .review: "Ready for review"
        case .plan: "Plan ready for review"
        case .merge: "Ready to merge"
        case .permission, .unknown: "Permission needed"
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
                .padding(.top, 7)
                .padding(.bottom, 5)
                if let title = permission.title {
                    Text(title)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                        .lineSpacing(1.5)
                }
                if let reason = permission.reason {
                    Text(reason)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .lineSpacing(1.5)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.top, 2)
                }
            }
            // A long rule moves Always allow under Approve and Reject before they stack.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 6) {
                    approve
                    reject
                    always
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        approve
                        reject
                    }
                    always
                }
                VStack(alignment: .leading, spacing: 6) {
                    approve
                    reject
                    always
                }
            }
            .padding(.top, 10)
        }
    }

    private var approve: some View {
        Button {
            shell.allow(approval)
        } label: {
            Text("Approve").grows(style)
        }
        .buttonStyle(.nest(.primary))
    }

    private var reject: some View {
        Button {
            shell.deny(approval)
        } label: {
            Text("Reject").grows(style)
        }
        .buttonStyle(.nest(.soft))
    }

    /// Names exactly what it allows; a long command is cut in the middle, whole in the help.
    private var always: some View {
        Button {
            shell.allow(approval, always: true)
        } label: {
            Text(approval.permission?.alwaysAllowTitle ?? "Always allow")
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .buttonStyle(.nest(.plain))
        .help(approval.permission?.alwaysAllowHelp ?? "Allow without asking again")
    }
}

/// The plan as rendered markdown, how the chat goes on after it (Auto-accept edits,
/// Approve edits manually, or Auto where the model offers it), an optional note, and
/// Approve plan or Keep planning (with the note).
private struct PlanBody: View {
    static let panelHeight: CGFloat = 260

    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell

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
            .background(Palette.soft, in: .rounded(Radius.row))
            .padding(.top, 8)
            let model = shell.sessions.session(approval.sessionID)?.model
            Segmented(
                options: shell.agents.planChoices(for: model).map { ($0, $0.planChoiceLabel) },
                selection: shell.approvals.planMode(for: approval)
            ) { shell.approvals.setPlanMode($0, for: approval) }
            .padding(.top, 8)
            .help("How Claude goes on once you approve the plan")
            CardField(placeholder: "Note for Claude (optional)", text: note) {
                shell.keepPlanning(approval)
            }
            .padding(.top, 8)
            ActionRow {
                Button {
                    shell.approvePlan(approval)
                } label: {
                    Text("Approve plan").grows(style)
                }
                .buttonStyle(.nest(.primary))
                .help("Continue with this plan in the mode chosen above")
                Button {
                    shell.keepPlanning(approval)
                } label: {
                    Text("Keep planning").grows(style)
                }
                .buttonStyle(.nest(.soft))
                .help("Send Claude back to planning, with the note if you wrote one")
            }
        }
    }

    private var plan: some View {
        let text = approval.plan?.plan ?? ""
        return SelectableText(key: text, linkColor: NSColor(Palette.Mac.link)) {
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
            .font(.mono(TypeSize.ui))
            .foregroundStyle(Palette.t1)
            .lineSpacing(2)
            .textSelection(.enabled)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.soft, in: .rounded(Radius.button))
    }
}

/// Each question with its options as radio rows (the recommended one marked and chosen
/// to start with), ending in Other with a field for the user's own answer, and Send
/// answer or Dismiss.
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
                        .font(.ui(TypeSize.reading, .medium))
                        .padding(.top, 6)
                        .padding(.bottom, 2)
                    OptionList(approval: approval, question: question)
                }
            }
            ActionRow {
                Button {
                    shell.answer(approval)
                } label: {
                    Text("Send answer").grows(style)
                }
                .buttonStyle(.nest(.primary))
                .disabled(!shell.approvals.canSubmitAnswers(approval))
                Button("Dismiss") { shell.dismiss(approval) }
                    .buttonStyle(.nest(.plain))
                    .fixedSize()
                    .help("Let Claude continue without an answer")
            }
        }
    }
}

/// A question's options, then Other (B60): choosing it shows a focused field under it
/// for the user's own answer. With one answer allowed Other replaces the options; with
/// several its text joins them.
private struct OptionList: View {
    let approval: Approval
    let question: Question
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        let approvals = shell.approvals
        let chosen = approvals.selection(for: approval, question: question)
        let other = approvals.isOtherChosen(for: approval, question: question)
        VStack(spacing: 4) {
            ForEach(question.options, id: \.label) { option in
                row(
                    on: chosen.contains(option.label), label: option.label,
                    recommended: option.recommended, description: option.description
                ) {
                    approvals.select(option.label, for: approval, question: question)
                }
            }
            row(on: other, label: "Other", recommended: false, description: nil) {
                approvals.chooseOther(for: approval, question: question)
            }
            if other {
                CardField(
                    placeholder: "Type your answer",
                    text: Binding(
                        get: { approvals.otherAnswer(for: approval, question: question) },
                        set: { approvals.answerOther($0, for: approval, question: question) }),
                    focusOnAppear: true)
            }
        }
        .padding(.top, 6)
    }

    private func row(
        on: Bool, label: String, recommended: Bool, description: String?,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 8) {
                mark(on: on, multiple: question.multiSelect)
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text(label).font(.ui(TypeSize.ui, .medium))
                        if recommended {
                            Text("Recommended")
                                .font(.ui(TypeSize.meta))
                                .foregroundStyle(StatusTone.review.color)
                        }
                    }
                    if let description {
                        Text(description)
                            .font(.ui(TypeSize.meta))
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
            .background(on ? accent.selection : Palette.soft, in: .rounded(Radius.row))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    @ViewBuilder private func mark(on: Bool, multiple: Bool) -> some View {
        RoundedRectangle(cornerRadius: multiple ? 3 : 6, style: .continuous)
            .strokeBorder(on ? accent.accent : Palette.t3, lineWidth: on ? 4 : 1.2)
            .frame(width: 12, height: 12)
            .padding(.top, 1.5)
    }
}

/// Stats, summary and files of the work, a feedback field, Send feedback and Approve;
/// a review has no Reject (B56).
private struct ReviewBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell
    @State private var feedback = ""

    var body: some View {
        let review = approval.review
        let session = shell.sessions.session(approval.sessionID)
        let git = shell.app.repo(approval.repo)?.git != false
        VStack(alignment: .leading, spacing: 0) {
            if style == .panel {
                Text(approval.title)
                    .font(.ui(TypeSize.ui, .medium))
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
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                        .lineSpacing(1.5)
                        .fixedSize(horizontal: false, vertical: true)
                }
                FileList(
                    paths: review?.paths ?? [], diff: shell.approvals.diffs[approval.sessionID])
            }
            if style == .panel {
                HStack(spacing: 6) {
                    // The review stays pending after feedback (B56), so the field clears.
                    CardField(placeholder: "Feedback for Claude", text: $feedback) {
                        send()
                    }
                    Button("Send") { send() }
                        .buttonStyle(.nest(.soft))
                        .fixedSize()
                        .disabled(feedback.trimmingCharacters(in: .whitespaces).isEmpty)
                        .help("Send feedback to the chat")
                }
                .padding(.top, 8)
            }
            ActionRow {
                Button {
                    shell.show(.publish(approval.id))
                } label: {
                    Text(PublishForm.approveTitle(for: session)).grows(style)
                }
                .buttonStyle(.nest(.primary))
                .disabled(!git)
                .help(git ? "" : "Not a git repository: nothing to commit")
            }
        }
    }
}

extension ReviewBody {
    fileprivate func send() {
        shell.sendFeedback(approval, text: feedback)
        feedback = ""
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
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.link)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let file {
                        HStack(spacing: 3) {
                            Text("+\(file.additions)").foregroundStyle(StatusTone.review.color)
                            Text("-\(file.deletions)").foregroundStyle(StatusTone.failed.color)
                        }
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                    }
                }
            }
            if paths.count > Self.shown {
                Text("and \(paths.count - Self.shown) more files")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
        }
        .padding(.top, 8)
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
        .padding(.top, 10)
    }
}

/// A one-line field on the card; Return submits when a handler is given.
struct CardField: View {
    let placeholder: String
    @Binding var text: String
    var submit: (() -> Void)?
    /// Takes the keyboard as soon as it shows, as Other's field does.
    var focusOnAppear = false
    @Environment(\.accentColors) private var accent
    @FocusState private var focused: Bool

    var body: some View {
        TextField("", text: $text)
            .accessibilityLabel(placeholder)
            .overlay(alignment: .leading) { Placeholder(text: placeholder, shown: text.isEmpty) }
            .textFieldStyle(.plain)
            .font(.ui(TypeSize.ui))
            .focused($focused)
            .onAppear { if focusOnAppear { focused = true } }
            .onSubmit { submit?() }
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(Palette.soft, in: .rounded(Radius.button))
            .overlay(
                RoundedRectangle.rounded(Radius.button)
                    .strokeBorder(focused ? accent.focus : Palette.divider, lineWidth: 1)
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

/// Text in the link color, such as "View changes"; underlined while hovered.
struct LinkButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.link)
                .underline(hovering)
                .padding(.horizontal, 4)
                .padding(.vertical, 2)
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

struct Switch: View {
    let isOn: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            Capsule()
                .fill(isOn ? StatusTone.review.color : Palette.selection)
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
    /// A card's main buttons keep their own small size, in the panel and the transcript
    /// alike (the look's flat buttons, B36); the style stays for the callers.
    func grows(_ style: ApprovalCard.Style) -> some View {
        fixedSize()
    }
}
