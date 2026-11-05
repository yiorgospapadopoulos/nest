import NestKit
import SwiftUI

/// What a subagent, pixie or team did in a chat, read-only (B46): the work view of the web
/// chat, live while it works (D151). There is no composer: follow-ups go in the chat.
struct WorkSheet: View {
    let target: WorkTarget
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.ui(TypeSize.body, .semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    shell.close()
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 10, weight: .medium))
                }
                .buttonStyle(.nest(.plain, iconOnly: true))
                .foregroundStyle(Palette.t3)
                .accessibilityLabel("Close \(title.lowercased())")
            }
            .padding(.leading, 18)
            .padding(.trailing, 10)
            .frame(height: 42)
            .overlay(alignment: .bottom) { Separator() }
            WebPage(target: .work(target), transient: true, label: "this work")
                .id(target)
        }
        .foregroundStyle(Palette.t1)
        .frame(width: 700, height: 720)
        .sheetSurface()
    }

    private var title: String {
        switch target {
        case .subagent(let chat, let tool):
            shell.activity.agents(session: chat).first { $0.id == tool }?.name ?? "Subagent"
        case .pixie(_, let id): shell.pixie(id)?.name ?? "Pixie"
        case .team(_, let id, _): shell.pixies.teams.first { $0.id == id }?.name ?? "Team"
        }
    }
}
