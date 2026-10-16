import NestKit
import SwiftUI

/// One row of the right panel's Needs you and Goals cards (B77): the status dot, the
/// chat's name (which opens it) over one grey line, and a chevron on the right, under the
/// card header's own, that opens the full item below.
/// Whether it is open stays with the shell under `key` while the app runs; until the user
/// toggles it, `openByDefault` decides.
struct FoldRow<Name: View, Line: View, Detail: View>: View {
    let key: String
    let tone: StatusTone
    var openByDefault = false
    @ViewBuilder let name: Name
    @ViewBuilder let line: Line
    @ViewBuilder let detail: Detail
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let open = shell.foldedRows[key] ?? openByDefault
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 8) {
                StatusDot(tone: tone).padding(.top, 5)
                VStack(alignment: .leading, spacing: 2) {
                    name
                        .font(.ui(TypeSize.ui, .medium))
                        .foregroundStyle(Palette.t1)
                    line
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    withAnimation(reduceMotion ? nil : .smooth(duration: 0.2)) {
                        shell.foldedRows[key] = !open
                    }
                } label: {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(open ? 0 : -90))
                        .frame(width: 20, height: 18)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .help(open ? "Hide details" : "Show details")
                .accessibilityLabel(open ? "Hide details" : "Show details")
            }
            .padding(EdgeInsets(top: 6, leading: 6, bottom: 6, trailing: 0))
            if open {
                detail
                    .padding(EdgeInsets(top: 0, leading: 20, bottom: 8, trailing: 0))
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A row's grey line: what it is, then a short detail.
struct NeedsLineText: View {
    let line: NeedsYouLine

    var body: some View {
        Text(line.detail.map { "\(line.kind) · \($0)" } ?? line.kind)
            .truncationMode(.tail)
    }
}
