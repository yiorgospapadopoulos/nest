import NestKit
import SwiftUI

/// Above a local chat's composer while its model is weak at tools (B106): the warning in the
/// wait colour, Change model and Don't show again, which this device keeps per model.
struct WeakToolsBar: View {
    let model: LocalModel
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            Image(systemName: Icon.warning)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(StatusTone.waiting.color)
            Text(LocalModelText.weakBar(model))
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            ChangeModelMenu(chat: chat, kind: .plain)
            Button("Don't show again") {
                withAnimation { shell.model.local.dismissWarning(model.id) }
            }
            .buttonStyle(.nest(.plain))
        }
        .padding(.leading, 11)
        .padding(.trailing, 4)
        .padding(.vertical, 4)
        .background(StatusTone.waiting.soft, in: .rounded(Radius.button))
        .accessibilityElement(children: .contain)
    }
}

/// A local chat's attach button opens a menu (B106): files, and what the model cannot take,
/// greyed with the reason: images without vision, and web search.
struct LocalAttachMenu: View {
    let model: LocalModel
    let attach: () -> Void

    var body: some View {
        Menu {
            Button("Attach files…", action: attach)
            if !model.vision {
                Button {
                } label: {
                    Text("Attach image")
                    Text(LocalModelText.noImages)
                }
                .disabled(true)
            }
            Button {
            } label: {
                Text("Web search")
                Text(LocalModelText.noWebSearch)
            }
            .disabled(true)
        } label: {
            Image(systemName: Icon.plus)
                .font(.system(size: 13, weight: .regular))
                .foregroundStyle(Palette.t3)
                .frame(width: Metrics.buttonHeight, height: Metrics.buttonHeight)
                .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize()
        .help("Attach")
        .accessibilityLabel("Attach")
    }
}

/// In a chat whose local server did not answer (B106): what is down, that the message is
/// kept, and Retry (sends it again), Start the app, and Change model.
struct ServerDownCard: View {
    let chat: String
    let down: LocalServerDown
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(LocalModelText.downTitle(down))
                .font(.ui(TypeSize.ui, .semibold))
                .foregroundStyle(StatusTone.failed.color)
            Text(LocalModelText.downBody(down))
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Button("Retry") { shell.send(chat) }
                    .buttonStyle(.nest(.primary))
                if let app = down.start {
                    Button(LocalModelText.start(app)) { shell.startLocal(app) }
                        .buttonStyle(.nest(.soft))
                        .disabled(shell.model.local.starting.contains(app))
                }
                ChangeModelMenu(chat: chat)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(StatusTone.failed.soft, in: .rounded(8))
        .accessibilityElement(children: .contain)
    }
}

/// "Local" in a thin outline, then "model · Engine", in a local chat's header (B106).
struct LocalChatLabel: View {
    let model: LocalModel
    let engine: String

    var body: some View {
        HStack(spacing: 6) {
            Text(LocalModelText.menuTitle)
                .font(.ui(10.5))
                .foregroundStyle(Palette.t2)
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .overlay(RoundedRectangle.rounded(4).strokeBorder(Palette.t3, lineWidth: 1))
            Text(LocalModelText.header(model, engine: engine))
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .fixedSize()
        .help(
            "Runs on \(model.name) at \(model.address), through \(LocalModelText.engineName(engine))"
        )
    }
}
