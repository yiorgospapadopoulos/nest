import HarnessKit
import SwiftUI

/// The window's sheets and popovers, drawn over its content: a scrim and a glass sheet,
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
                        .padding(.top, TabStrip.height + 8)
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
        case .settings:
            SettingsSheet().padding(.top, 70)
        case .connectors:
            ConnectorsSheet().padding(.top, 70)
        case .diff(let id):
            DiffSheet(approvalID: id).padding(.vertical, 40).padding(.horizontal, 48)
        case .publish(let id):
            PublishSheet(approvalID: id).padding(.top, 70)
        case .usage:
            EmptyView()
        }
    }
}

/// A glass sheet with a title, a close button and scrolling content.
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
                    .font(.ui(TypeSize.headline, .bold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button {
                    shell.close()
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 12, weight: .medium))
                }
                .buttonStyle(.harness(.ghost, iconOnly: true))
                .accessibilityLabel("Close \(title.lowercased())")
            }
            .padding(EdgeInsets(top: 14, leading: 22, bottom: 12, trailing: 14))
            .overlay(alignment: .bottom) { Rectangle().fill(Palette.hair).frame(height: 1) }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) { content() }
                        .padding(EdgeInsets(top: 4, leading: 22, bottom: 20, trailing: 22))
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
        .sheetGlass(radius: DesignTokens.Radius.sheet)
        .shadow(color: Palette.glassShadow, radius: 30, y: 18)
    }
}

/// An uppercase section head of a sheet.
struct SheetSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title.uppercased())
                .font(.ui(TypeSize.caption, .bold))
                .tracking(0.66)
                .foregroundStyle(Palette.t3)
                .padding(.top, 18)
                .padding(.bottom, 6)
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
        HStack(spacing: 14) {
            Text(label).font(.ui(TypeSize.body))
            Spacer(minLength: 8)
            control()
        }
        .padding(.vertical, 9)
        .overlay(alignment: .top) {
            if !first {
                Rectangle().fill(Palette.hair).frame(height: 1)
            }
        }
    }
}

/// A small segmented control, as the mockup's `.mseg`.
struct Segmented<Value: Hashable>: View {
    let options: [(Value, String)]
    let selection: Value
    let select: (Value) -> Void

    var body: some View {
        HStack(spacing: 0) {
            ForEach(options, id: \.0) { value, title in
                let on = value == selection
                Button {
                    select(value)
                } label: {
                    Text(title)
                        .font(.ui(TypeSize.small, .semibold))
                        .foregroundStyle(on ? Palette.t1 : Palette.t2)
                        .padding(.horizontal, 11)
                        .frame(height: 26)
                        .background {
                            if on {
                                RoundedRectangle(cornerRadius: 7, style: .continuous)
                                    .fill(Palette.glassStrong)
                                    .shadow(color: Palette.glassShadow, radius: 1.5, y: 1)
                            }
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(2)
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
    }
}
