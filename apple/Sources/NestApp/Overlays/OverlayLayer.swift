import NestKit
import SwiftUI

/// The window's sheets and popovers, drawn over its content: a scrim and a sheet,
/// or the usage popover under its button. Esc or a click outside closes them.
struct OverlayLayer: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        if let overlay = shell.overlay {
            ZStack(alignment: .top) {
                if overlay == .usage {
                    Color.clear
                        .contentShape(Rectangle())
                        .onTapGesture { shell.close() }
                    UsagePopover()
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .padding(.trailing, UsagePopover.trailingInset)
                        .padding(.top, Metrics.stripHeight + 8)
                        .transition(.opacity.combined(with: .offset(y: -6)))
                } else {
                    Palette.scrim
                        .ignoresSafeArea()
                        .onTapGesture { shell.close() }
                        .transition(.opacity)
                    sheet(overlay)
                        .transition(.opacity.combined(with: .offset(y: -8)))
                }
                // Esc closes whatever is open, wherever the focus is.
                Button("Close") { shell.close() }
                    .keyboardShortcut(.cancelAction)
                    .opacity(0)
                    .frame(width: 0, height: 0)
                    .accessibilityHidden(true)
            }
        }
    }

    @ViewBuilder private func sheet(_ overlay: Overlay) -> some View {
        switch overlay {
        case .palette:
            PaletteView().padding(.top, 96)
        case .diff(let id):
            DiffSheet(approvalID: id).padding(.vertical, 40).padding(.horizontal, 48)
        case .publish(let id):
            PublishSheet(approvalID: id).padding(.top, 70)
        case .rewind:
            RewindSheet().padding(.top, 70)
        case .habitRun(let session):
            HabitRunSheet(session: session).padding(.top, 60)
        case .image(let id):
            ImageSheet(attachment: id).padding(.vertical, 40).padding(.horizontal, 48)
        case .work:
            WorkSheet().padding(.vertical, 40)
        case .usage:
            EmptyView()
        }
    }
}

/// A sheet with a title, a close button and scrolling content.
struct SheetFrame<Content: View>: View {
    let title: String
    var width: Double = 580
    var maxHeight: Double = 700
    /// A view id inside the content to bring into view when it appears.
    var scrollTarget: String?
    @ViewBuilder let content: () -> Content
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
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) { content() }
                        .padding(EdgeInsets(top: 2, leading: 18, bottom: 16, trailing: 18))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .scrollIndicators(.never)
                .onChange(of: scrollTarget, initial: true) { _, target in
                    if let target {
                        withAnimation(.smooth(duration: 0.3)) {
                            proxy.scrollTo(target, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(width: width)
        .frame(maxHeight: maxHeight)
        .fixedSize(horizontal: false, vertical: true)
        .sheetSurface()
    }
}

/// A small grey section label of a sheet, over its rows.
struct SheetSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.top, 14)
                .padding(.bottom, 2)
            content()
        }
    }
}

/// A label on the left and a control on the right, with a hairline above when it
/// follows another row.
struct SheetRow<Control: View>: View {
    let label: String
    var first = false
    @ViewBuilder let control: () -> Control

    var body: some View {
        HStack(spacing: 12) {
            Text(label).font(.ui(TypeSize.ui))
            Spacer(minLength: 8)
            control()
        }
        .frame(minHeight: 32)
        .padding(.vertical, 2)
        .overlay(alignment: .top) {
            if !first {
                Separator()
            }
        }
    }
}

/// A small segmented control: flat segments, the chosen one on the selection fill.
struct Segmented<Value: Hashable>: View {
    let options: [(Value, String)]
    let selection: Value
    let select: (Value) -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { value, title in
                let on = value == selection
                Button {
                    select(value)
                } label: {
                    Text(title)
                        .font(.ui(TypeSize.button))
                        .foregroundStyle(on ? Palette.t1 : Palette.t2)
                        .padding(.horizontal, 9)
                        .frame(height: Metrics.buttonHeight)
                        .background(on ? accent.selection : .clear, in: .rounded(Radius.button))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }
}
