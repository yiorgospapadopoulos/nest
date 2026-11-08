import NestKit
import SwiftUI

/// The window's sheets and popovers, drawn over its content: a scrim and a sheet,
/// or the usage popover under its button. Esc or a click outside closes them.
struct OverlayLayer: View {
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

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
                        .modal(Self.name(of: overlay))
                        .transition(slide(-6))
                } else {
                    Palette.scrim
                        .ignoresSafeArea()
                        .onTapGesture { shell.close() }
                        .transition(.opacity)
                        .accessibilityHidden(true)
                    sheet(overlay)
                        .modal(Self.name(of: overlay))
                        .transition(slide(-8))
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

    private func slide(_ offset: Double) -> AnyTransition {
        reduceMotion ? .opacity : .opacity.combined(with: .offset(y: offset))
    }

    /// What VoiceOver calls the open sheet.
    static func name(of overlay: Overlay) -> String {
        switch overlay {
        case .palette: "Search"
        case .usage: "Usage"
        case .diff: "Changes"
        case .publish: "Approve"
        case .rewind: "Rewind"
        case .habitRun: "Habit run"
        case .image: "Image"
        case .work: "Work"
        case .branchTree: "Branch map"
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
        case .work(let target):
            WorkSheet(target: target).padding(.vertical, 40)
        case .branchTree(let project):
            BranchTreeSheet(project: project)
                .padding(.vertical, 40)
                .frame(maxHeight: .infinity)
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
    /// False when the content holds its own scroll box and fills the sheet.
    var scrolls = true
    @ViewBuilder let content: () -> Content
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text(title)
                    .font(.ui(TypeSize.body, .semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.isHeader)
                SheetCloseButton(label: "Close \(title.lowercased())") { shell.close() }
                    .foregroundStyle(Palette.t3)
            }
            .padding(.leading, 18)
            .padding(.trailing, 10)
            .frame(height: 42)
            .overlay(alignment: .bottom) { Separator() }
            if scrolls {
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
            } else {
                VStack(alignment: .leading, spacing: 0) { content() }
                    .frame(maxHeight: .infinity, alignment: .top)
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(width: width)
        .frame(maxHeight: maxHeight)
        .fixedSize(horizontal: false, vertical: scrolls)
        .sheetSurface()
    }
}

/// A sheet's x. It takes the keyboard as the sheet opens, so Tab starts inside the sheet
/// rather than in the window under it.
struct SheetCloseButton: View {
    let label: String
    var kind = NestButtonStyle.Kind.plain
    let close: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        Button(action: close) {
            Image(systemName: Icon.close).font(.system(size: 10, weight: .medium))
        }
        .buttonStyle(.nest(kind, iconOnly: true))
        .accessibilityLabel(label)
        .focused($focused)
        .task {
            // Once the button is in the window, as the composer's focus waits.
            await Task.yield()
            focused = true
        }
    }
}

extension View {
    /// A sheet or popover over the window, as VoiceOver should see it: one named group, the
    /// window under it hidden (`ShellView`), so VoiceOver lands and stays in it. Moving
    /// VoiceOver's focus here as well took the keyboard from the palette's field (B147).
    func modal(_ name: String) -> some View {
        accessibilityElement(children: .contain)
            .accessibilityAddTraits(.isModal)
            .accessibilityLabel(name)
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
/// Filling the width, the segments share it equally.
struct Segmented<Value: Hashable>: View {
    let options: [(Value, String)]
    let selection: Value
    var fillsWidth = false
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
                        .frame(maxWidth: fillsWidth ? .infinity : nil)
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
