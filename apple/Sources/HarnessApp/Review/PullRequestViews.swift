import HarnessKit
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
                Image(systemName: Icon.pullRequest).font(.system(size: 9, weight: .medium))
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

/// The pull request's title and state, its checks, Refresh and Open on GitHub.
struct PRDetails: View {
    let session: String
    let pr: PullRequest
    @Environment(Shell.self) private var shell

    var body: some View {
        let refreshing = shell.sessions.refreshingPR.contains(session)
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(pr.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .fixedSize(horizontal: false, vertical: true)
                Text(
                    "#\(String(pr.number)) · \(PRBadge.stateLabel(pr.state)) · \(PRBadge.checksSummary(pr.checks))"
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
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
            HStack(spacing: 6) {
                Button {
                    shell.refreshPR(session)
                } label: {
                    HStack(spacing: 6) {
                        if refreshing {
                            ProgressView().controlSize(.mini)
                        } else {
                            Image(systemName: Icon.refresh)
                        }
                        Text("Refresh")
                    }
                }
                .buttonStyle(.harness(.soft))
                .disabled(refreshing)
                .help("Read the pull request from GitHub now")
                Spacer(minLength: 0)
                Button {
                    shell.openOnGitHub(pr.url)
                } label: {
                    Label("Open on GitHub", systemImage: Icon.open)
                }
                .buttonStyle(.harness(.plain))
            }
        }
        .padding(14)
        .frame(width: 300, alignment: .leading)
    }
}

/// One check: its dot, its name, and a link to its run when GitHub gives one.
private struct CheckRow: View {
    let check: PRCheck
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 8) {
            StatusDot(tone: tone, hollow: check.state == .skipped)
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
                .buttonStyle(.harness(.plain, height: 20, iconOnly: true))
                .help("Open the run")
                .accessibilityLabel("Open \(check.name)")
            }
        }
        .padding(.horizontal, 8)
        .frame(minHeight: Metrics.rowHeight)
    }

    private var tone: StatusTone {
        switch check.state {
        case .pending: .waiting
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
/// methods in a menu, and Dismiss.
struct MergeBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell

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
                        shell.merge(approval)
                    } label: {
                        Label("Merge (squash)", systemImage: Icon.merge).grows(style)
                    }
                    .buttonStyle(.harness(.primary))
                    Menu {
                        ForEach(MergeMethod.allCases, id: \.self) { method in
                            Button(method.label) { shell.merge(approval, method: method) }
                        }
                    } label: {
                        Image(systemName: Icon.chevron).font(.system(size: 9, weight: .bold))
                    }
                    .menuStyle(.button)
                    .buttonStyle(.harness(.primary))
                    .menuIndicator(.hidden)
                    .fixedSize()
                    .help("Merge method")
                    .accessibilityLabel("Merge method")
                }
                Button("Dismiss") { shell.dismiss(approval) }
                    .buttonStyle(.harness(.plain))
                    .fixedSize()
                    .help("Hide this until the pull request changes")
            }
        }
    }
}

/// A chat whose pull request has failed checks: their names and Send to agent.
struct ChecksFailedCard: View {
    let session: Session
    @Environment(Shell.self) private var shell

    var body: some View {
        let failing = session.pr?.failingChecks ?? []
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                StatusDot(tone: .failed)
                Text("Checks failed")
                Spacer(minLength: 8)
                ChatLink(chat: session.id, title: session.title)
                    .foregroundStyle(Palette.t3)
                    .frame(maxWidth: 150, alignment: .trailing)
            }
            .font(.ui(TypeSize.meta))
            .foregroundStyle(StatusTone.failed.color)
            if let pr = session.pr {
                Text("#\(String(pr.number)) \(pr.title)")
                    .font(.ui(TypeSize.ui, .medium))
                    .lineLimit(1)
                    .padding(.top, 7)
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
                .buttonStyle(.harness(.primary))
                .help("harness reads the failing checks' logs and sends them to the chat")
                if let pr = session.pr {
                    Button("Open on GitHub") { shell.openOnGitHub(pr.url) }
                        .buttonStyle(.harness(.plain))
                        .fixedSize()
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
