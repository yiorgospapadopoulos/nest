import NestKit
import SwiftUI

/// "#12" with the checks dot; a click shows the checks, Refresh and Open on GitHub.
struct PRChip: View {
    let session: String
    let pr: PullRequest
    @State private var showsDetails = false

    var body: some View {
        let dot = PRBadge.dot(of: pr)
        Button {
            showsDetails.toggle()
        } label: {
            HStack(spacing: 5) {
                PullRequestGlyph(size: 11)
                Text("#\(String(pr.number))")
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
                StatusDot(tone: dot.tone, hollow: dot.hollow)
            }
            .foregroundStyle(Palette.t2)
            .padding(.horizontal, 6)
            .frame(height: 20)
            .background(Palette.soft, in: .rounded(Radius.chip))
            .contentShape(.rounded(Radius.chip))
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .fixedSize()
        .help("Pull request #\(String(pr.number)): \(PRBadge.checksSummary(pr.checks))")
        .accessibilityLabel(
            "Pull request \(pr.number), \(PRBadge.stateLabel(pr.state)), \(PRBadge.checksSummary(pr.checks))"
        )
        .popover(isPresented: $showsDetails, arrowEdge: .bottom) {
            PRDetails(session: session, pr: pr)
        }
    }
}

/// GitHub's pull request mark, drawn: a branch from one commit to another on the left and,
/// on the right, a line from the pull request's head turning back into it with an arrow.
/// The symbol of the same name reads as a branch at the chip's size (B101).
struct PullRequestGlyph: View {
    let size: CGFloat

    var body: some View {
        Canvas { context, canvas in
            let s = canvas.width
            let line = max(1, s * 0.11)
            let radius = s * 0.12
            func ring(_ x: CGFloat, _ y: CGFloat) -> Path {
                Path(
                    ellipseIn: CGRect(
                        x: x * s - radius, y: y * s - radius, width: radius * 2,
                        height: radius * 2))
            }
            var path = ring(0.25, 0.2)
            path.addPath(ring(0.25, 0.8))
            path.addPath(ring(0.75, 0.8))
            path.move(to: CGPoint(x: 0.25 * s, y: 0.2 * s + radius))
            path.addLine(to: CGPoint(x: 0.25 * s, y: 0.8 * s - radius))
            path.move(to: CGPoint(x: 0.75 * s, y: 0.8 * s - radius))
            path.addLine(to: CGPoint(x: 0.75 * s, y: 0.38 * s))
            path.addQuadCurve(
                to: CGPoint(x: 0.57 * s, y: 0.2 * s), control: CGPoint(x: 0.75 * s, y: 0.2 * s))
            path.addLine(to: CGPoint(x: 0.45 * s, y: 0.2 * s))
            path.move(to: CGPoint(x: 0.56 * s, y: 0.09 * s))
            path.addLine(to: CGPoint(x: 0.45 * s, y: 0.2 * s))
            path.addLine(to: CGPoint(x: 0.56 * s, y: 0.31 * s))
            context.stroke(
                path, with: .foreground,
                style: StrokeStyle(lineWidth: line, lineCap: .round, lineJoin: .round))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// Open on GitHub: plain, in the link colour with its icon, so it reads as active.
struct OpenOnGitHubButton: View {
    let url: String
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.openOnGitHub(url)
        } label: {
            Label("Open on GitHub", systemImage: Icon.open)
        }
        .buttonStyle(.nest(.link))
        .fixedSize()
    }
}

/// "#118" with the open issue mark, beside the pull request's chip in a chat's header: the
/// issue the chat was started from, opened on GitHub with a click (B101).
struct IssueChip: View {
    let issue: IssueRef
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.openOnGitHub(issue.url)
        } label: {
            HStack(spacing: 5) {
                Image(systemName: Icon.issue).font(.system(size: 9, weight: .medium))
                Text("#\(String(issue.number))")
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
            }
            .foregroundStyle(Palette.t2)
            .padding(.horizontal, 6)
            .frame(height: 20)
            .background(Palette.soft, in: .rounded(Radius.chip))
            .contentShape(.rounded(Radius.chip))
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .fixedSize()
        .help("Issue #\(String(issue.number)): \(issue.title). Open on GitHub")
        .accessibilityLabel("Issue \(issue.number), \(issue.title)")
    }
}

/// The pull request with its state and, for a chat from an issue, the issue it closes on
/// merge below it, an arrow pointing up from the issue to the pull request; then its
/// checks, whether review comments go to the agent on their own, Refresh and Open on
/// GitHub.
struct PRDetails: View {
    let session: String
    let pr: PullRequest
    @Environment(Shell.self) private var shell

    var body: some View {
        let refreshing = shell.sessions.refreshingPR.contains(session)
        let chat = shell.sessions.session(session)
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                LinkLine(
                    number: pr.number, title: pr.title, url: pr.url,
                    help: "Open the pull request on GitHub"
                ) {
                    PullRequestGlyph(size: 12)
                }
                if let issue = chat?.issue {
                    HStack(spacing: 8) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 10, weight: .semibold))
                            .frame(width: 12)
                        Text(PRBadge.closes(issue))
                            .font(.ui(TypeSize.meta))
                    }
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 1)
                    LinkLine(
                        number: issue.number, title: issue.title, url: issue.url,
                        help: "Open the issue on GitHub"
                    ) {
                        Image(systemName: Icon.issue).font(.system(size: 11, weight: .medium))
                    }
                }
                // Under the issue, the line names the pull request it describes.
                Text(
                    (chat?.issue == nil ? "" : "#\(String(pr.number)) \u{00B7} ")
                        + PRBadge.statusLine(pr)
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.leading, 20)
                .padding(.top, chat?.issue == nil ? 0 : 2)
            }
            if !pr.checks.items.isEmpty {
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(Array(pr.checks.items.enumerated()), id: \.offset) { _, check in
                        CheckRow(check: check)
                    }
                }
                .padding(.vertical, 2)
                .softFill()
            }
            if let chat, pr.state == .open {
                let on = PRBadge.autoSends(chat)
                HStack(alignment: .center, spacing: 10) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(PRBadge.autoSendTitle)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t1)
                        Text(PRBadge.autoSendDetail(on))
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    Spacer(minLength: 0)
                    Switch(isOn: on, accent: true) { shell.setReviewAutoSend(session, !on) }
                        .accessibilityLabel(PRBadge.autoSendTitle)
                }
            }
            HStack(spacing: 6) {
                Button {
                    shell.refreshPR(session)
                } label: {
                    HStack(spacing: 6) {
                        if refreshing {
                            Fireflies(height: 9)
                        } else {
                            Image(systemName: Icon.refresh)
                        }
                        Text("Refresh")
                    }
                }
                .buttonStyle(.nest(.soft))
                .disabled(refreshing)
                .help("Read the pull request from GitHub now")
                Spacer(minLength: 0)
                OpenOnGitHubButton(url: pr.url)
            }
        }
        .padding(14)
        .frame(width: 300, alignment: .leading)
    }
}

/// One line of the popover's header: the mark, the grey number and the title, opening it on
/// GitHub with a click.
private struct LinkLine<Mark: View>: View {
    let number: Int
    let title: String
    let url: String
    let help: String
    @ViewBuilder let mark: Mark
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.openOnGitHub(url)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                mark
                    .foregroundStyle(Palette.t2)
                    .frame(width: 12)
                    .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                Text("#\(String(number))")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .monospacedDigit()
                Text(title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(help)
    }
}

/// One check: its dot, its name, and a link to its run when GitHub gives one.
private struct CheckRow: View {
    let check: PRCheck
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 8) {
            StatusMark(tone: tone, hollow: check.state == .skipped)
            Text(check.name)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(label)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            if let url = check.url {
                Button {
                    shell.openOnGitHub(url)
                } label: {
                    Image(systemName: Icon.open).font(.system(size: 10))
                }
                .buttonStyle(.nest(.plain, height: 20, iconOnly: true))
                .help("Open the run")
                .accessibilityLabel("Open \(check.name)")
            }
        }
        .padding(.horizontal, 8)
        .frame(minHeight: Metrics.rowHeight)
    }

    private var tone: StatusTone {
        switch check.state {
        // Still running: the fireflies in the dot's place.
        case .pending: .running
        case .success, .skipped: .review
        case .failure: .failed
        case .unknown: .done
        }
    }

    private var label: String {
        switch check.state {
        case .pending: "Running"
        case .success: "Passed"
        case .skipped: "Skipped"
        case .failure: "Failed"
        case .unknown: ""
        }
    }
}

/// The merge approval's body: the pull request, its checks, Merge (squash) with the other
/// methods in a menu, "Also delete the branch" (unticked for each card; Nest deletes no
/// branch otherwise, B96), and Dismiss.
struct MergeBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell
    @State private var deletesBranch = false

    var body: some View {
        let proposal = approval.merge
        VStack(alignment: .leading, spacing: 0) {
            if let proposal {
                Button {
                    shell.openOnGitHub(proposal.url)
                } label: {
                    HStack(spacing: 6) {
                        Text("#\(String(proposal.number))")
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t3)
                            .monospacedDigit()
                        Text(proposal.title)
                            .font(.ui(TypeSize.ui, .medium))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .help("Open on GitHub")
                .padding(.top, 7)
                HStack(spacing: 6) {
                    StatusDot(
                        tone: proposal.checks.state == .success ? .review : .done,
                        hollow: proposal.checks.state != .success)
                    Text(
                        proposal.checks.state == .success
                            ? "Checks passed: \(PRBadge.checksSummary(proposal.checks))"
                            : PRBadge.checksSummary(proposal.checks))
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
                .padding(.top, 5)
            }
            ActionRow {
                HStack(spacing: 1) {
                    Button {
                        shell.merge(approval, deleteBranch: deletesBranch)
                    } label: {
                        Label("Merge (squash)", systemImage: Icon.merge).grows(style)
                    }
                    .buttonStyle(.nest(.primary))
                    Menu {
                        ForEach(MergeMethod.allCases, id: \.self) { method in
                            Button(method.label) {
                                shell.merge(approval, method: method, deleteBranch: deletesBranch)
                            }
                        }
                    } label: {
                        Image(systemName: Icon.chevron).font(.system(size: 9, weight: .bold))
                    }
                    .menuStyle(.button)
                    .buttonStyle(.nest(.primary))
                    .menuIndicator(.hidden)
                    .fixedSize()
                    .help("Merge method")
                    .accessibilityLabel("Merge method")
                }
                Toggle("Also delete the branch", isOn: $deletesBranch)
                    .toggleStyle(.checkbox)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t1)
                    .fixedSize()
                    .help("Delete the pull request's branch on GitHub after merging")
                Button("Dismiss") { shell.dismiss(approval) }
                    .buttonStyle(.nest(.plain))
                    .fixedSize()
                    .help("Hide this until the pull request changes")
            }
        }
        .onChange(of: approval.id) { deletesBranch = false }
    }
}

/// The review comments approval's body (B101): the pull request, each comment's file and
/// line in mono (the full path in its help) with Send for that comment alone, over its
/// text; Send all to agent and Open on GitHub.
struct ReviewCommentsBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell

    var body: some View {
        let request = approval.reviewComments
        VStack(alignment: .leading, spacing: 0) {
            if let request {
                Text(
                    "#\(String(request.number))"
                        + (request.changesRequested ? " \u{00B7} Changes requested" : "")
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .monospacedDigit()
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(request.comments) { comment in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(comment.shortLocation)
                                    .font(.mono(TypeSize.meta))
                                    .foregroundStyle(Palette.t2)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                    .help(comment.location)
                                Spacer(minLength: 0)
                                Button("Send") { shell.sendReviewComment(comment, of: approval) }
                                    .buttonStyle(.nest(.plain, height: 20))
                                    .fixedSize()
                                    .disabled(
                                        shell.approvals.sendingComments.contains(comment.id)
                                    )
                                    .help("Send only this comment to the agent")
                                    .accessibilityLabel("Send \(comment.shortLocation)")
                            }
                            Text(comment.body)
                                .font(.ui(TypeSize.ui))
                                .foregroundStyle(Palette.t1)
                                .lineLimit(6)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.top, 6)
            }
            ActionRow {
                Button {
                    shell.sendReviewComments(approval)
                } label: {
                    Label("Send all to agent", systemImage: Icon.send).grows(style)
                }
                .buttonStyle(.nest(.primary))
                .help("Nest sends these comments to the chat; nothing is written on GitHub")
                if let request {
                    OpenOnGitHubButton(url: request.url)
                }
            }
        }
    }
}

/// A chat whose pull request has failed checks: their names and Send to agent, under its
/// Needs you row, which names the chat (B77).
struct ChecksFailedCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        let failing = session.pr?.failingChecks ?? []
        VStack(alignment: .leading, spacing: 0) {
            if let pr = session.pr {
                Text("#\(String(pr.number)) \(pr.title)")
                    .font(.ui(TypeSize.ui, .medium))
                    .lineLimit(1)
            }
            VStack(alignment: .leading, spacing: 4) {
                ForEach(failing, id: \.self) { name in
                    HStack(spacing: 7) {
                        StatusDot(tone: .failed)
                        Text(name)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(Palette.t2)
                            .lineLimit(1)
                    }
                }
            }
            .padding(.top, 6)
            ActionRow {
                Button {
                    shell.sendChecksFailure(session)
                } label: {
                    Label("Send to agent", systemImage: Icon.send).grows(.panel)
                }
                .buttonStyle(.nest(.primary))
                .help("Nest reads the failing checks' logs and sends them to the chat")
                if let pr = session.pr {
                    OpenOnGitHubButton(url: pr.url)
                }
            }
        }
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
    }
}
