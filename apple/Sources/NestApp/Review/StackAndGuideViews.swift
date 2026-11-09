import NestKit
import SwiftUI

/// The pull request popover's branch to move (B149): where it goes, why it could not yet,
/// and Push, Rebase and push or Rebase.
struct RestackRows: View {
    let chat: Session
    let restack: Restack
    @Environment(Shell.self) private var shell

    var body: some View {
        let action = RestackAction(restack, of: chat)
        let busy = shell.sessions.restacking.contains(chat.id)
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(restack.line)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t1)
                if let error = restack.error {
                    StepError(text: error)
                }
            }
            Spacer(minLength: 0)
            Button {
                shell.restack(chat, action)
            } label: {
                HStack(spacing: 6) {
                    if busy {
                        Fireflies(height: 9)
                    }
                    Text(action.title)
                }
            }
            .buttonStyle(.nest(.soft))
            .fixedSize()
            .disabled(busy)
            .help(action.help)
        }
    }
}

/// The pull request popover's review guide (B149): Write review guide, writing, then Open
/// review guide and Post on GitHub, or the posted comment; Write again after new commits.
struct ReviewGuideRows: View {
    let chat: Session
    let pr: PullRequest
    @Environment(Shell.self) private var shell

    var body: some View {
        let busy = shell.sessions.guideBusy.contains(chat.id)
        VStack(alignment: .leading, spacing: 6) {
            switch ReviewGuideRow(chat.prGuide, pr: pr) {
            case .write:
                write("Write review guide")
            case .writing:
                HStack(spacing: 6) {
                    Fireflies(height: 9)
                    Text("Writing review guide")
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
            case .failed(let error):
                if let error {
                    StepError(text: error)
                }
                write("Try again")
            case .ready(let artifact, let commentURL, let outdated):
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 6) {
                        open(artifact)
                        post(commentURL)
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        open(artifact)
                        post(commentURL)
                    }
                }
                if outdated {
                    write("Write again")
                        .help("The pull request has new commits since the guide was written")
                }
            }
        }
        .disabled(busy)
    }

    private func write(_ title: String) -> some View {
        Button(title) { shell.writeReviewGuide(chat.id) }
            .buttonStyle(.nest(.soft))
            .fixedSize()
            .help("An agent reads the pull request and writes a guide for reviewing it")
    }

    private func open(_ artifact: String) -> some View {
        Button {
            shell.openArtifact(artifact, version: nil, from: chat.id)
        } label: {
            Label("Open review guide", systemImage: Icon.artifact)
        }
        .buttonStyle(.nest(.soft))
        .fixedSize()
    }

    @ViewBuilder private func post(_ commentURL: String?) -> some View {
        if let commentURL {
            Button {
                shell.openOnGitHub(commentURL)
            } label: {
                Label("Posted on GitHub", systemImage: Icon.open)
            }
            .buttonStyle(.nest(.link))
            .fixedSize()
            .help("Open the guide's comment on GitHub")
        } else {
            Button("Post on GitHub") { shell.postReviewGuide(chat.id) }
                .buttonStyle(.nest(.plain))
                .fixedSize()
                .help("Post the guide as a comment on the pull request")
        }
    }
}

/// Why a step could not happen, in the failed colour over as many lines as it needs.
private struct StepError: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(StatusTone.failed.color)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// The restack approval's body (B149): the pull request's number and where its branch
/// moved, why it could not when it failed, Push, Rebase and push or Rebase, and Dismiss.
struct RestackBody: View {
    let approval: Approval
    let style: ApprovalCard.Style
    @Environment(Shell.self) private var shell

    var body: some View {
        let request = approval.restack
        VStack(alignment: .leading, spacing: 0) {
            if let request {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if let number = request.number {
                        Text("#\(String(number))")
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t3)
                            .monospacedDigit()
                    }
                    Text(request.headline)
                        .font(.ui(TypeSize.ui, .medium))
                        .foregroundStyle(Palette.t1)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                .padding(.top, 7)
                if let error = request.error {
                    StepError(text: error)
                        .padding(.top, 5)
                }
            }
            ActionRow {
                if let request {
                    let action = RestackAction(request)
                    Button {
                        shell.restack(approval, action)
                    } label: {
                        Label {
                            Text(action.title)
                        } icon: {
                            BranchIcon(size: 11)
                        }
                        .grows(style)
                    }
                    .buttonStyle(.nest(.primary))
                    .help(action.help)
                }
                Button("Dismiss") { shell.dismiss(approval) }
                    .buttonStyle(.nest(.plain))
                    .fixedSize()
                    .help("Hide this; the branch stays where it is")
            }
        }
    }
}
