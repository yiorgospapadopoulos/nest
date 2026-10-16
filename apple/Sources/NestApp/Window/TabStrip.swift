import AppKit
import NestKit
import SwiftUI

/// The Pixies tab and the project tabs across the top of the window, with the usage meter
/// and search. Windowed, the strip leaves room for the traffic lights; in full screen
/// there are none, and the Pixies tab sits at the left edge.
struct TabStrip: View {
    /// Room for the window's traffic lights.
    static let leadingInset = 86.0
    /// The left edge in full screen, as on the right.
    static let fullScreenInset = 10.0
    let fullScreen: Bool
    /// A tab's height inside the strip.
    static let tabHeight = 24.0
    /// The space between tabs.
    static let spacing = 2.0

    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var addingProject = false
    /// Add folder was picked: the panel opens once the popover has gone.
    @State private var choosingFolder = false
    /// The project tab being dragged to a new place, if any.
    @State private var drag: TabDrag?
    /// One project tab's width plus the spacing; every project tab has the same width.
    @State private var tabStep = 0.0

    var body: some View {
        HStack(spacing: Self.spacing) {
            PixiesTab()
            Rectangle()
                .fill(Palette.divider)
                .frame(width: 1, height: 16)
                .padding(.horizontal, 6)
                .accessibilityHidden(true)
            let tabs = shell.app.openProjects
            ForEach(Array(tabs.enumerated()), id: \.element) { index, name in
                let dragged = drag?.name == name
                ProjectTab(name: name) { by in
                    shell.app.moveProject(name, to: index + by)
                }
                .onGeometryChange(for: Double.self) {
                    $0.size.width
                } action: {
                    tabStep = $0 + Self.spacing
                }
                .offset(x: offset(of: index, dragged: dragged, count: tabs.count))
                .zIndex(dragged ? 1 : 0)
                .animation(
                    dragged || reduceMotion ? nil : .smooth(duration: 0.18),
                    value: drag.map { target(of: $0, count: tabs.count) }
                )
                .highPriorityGesture(reorder(name, at: index, count: tabs.count))
            }
            addButton
            Spacer(minLength: 12)
            // The meter and search keep their size; the project tabs shrink first.
            UsageButton().fixedSize().padding(.trailing, 6)
            SearchButton().fixedSize()
        }
        .padding(.leading, fullScreen ? Self.fullScreenInset : Self.leadingInset)
        .padding(.trailing, 10)
        .frame(height: Metrics.stripHeight)
        .background(WindowDragArea())
    }

    /// Where the dragged tab would land now.
    private func target(of drag: TabDrag, count: Int) -> Int {
        TabReorder.target(
            from: drag.start, translation: drag.translation, step: tabStep, count: count)
    }

    /// The dragged tab follows the pointer; the tabs it passes slide aside.
    private func offset(of index: Int, dragged: Bool, count: Int) -> Double {
        guard let drag else { return 0 }
        if dragged {
            return drag.translation
        }
        return TabReorder.offset(
            of: index, from: drag.start, to: target(of: drag, count: count), step: tabStep)
    }

    /// Drags a project tab along the strip, Safari style. It goes first so a moving click
    /// drags; a click that does not move 4 points still selects the tab or closes it.
    private func reorder(_ name: String, at index: Int, count: Int) -> some Gesture {
        DragGesture(minimumDistance: 4, coordinateSpace: .global)
            .onChanged { value in
                drag = TabDrag(name: name, start: index, translation: value.translation.width)
            }
            .onEnded { value in
                let landing = TabDrag(
                    name: name, start: index, translation: value.translation.width)
                withAnimation(reduceMotion ? nil : .smooth(duration: 0.18)) {
                    shell.app.moveProject(name, to: target(of: landing, count: count))
                    drag = nil
                }
            }
    }

    private var addButton: some View {
        Button {
            addingProject.toggle()
        } label: {
            Image(systemName: Icon.plus).font(.system(size: 12, weight: .regular))
        }
        .buttonStyle(StripIconStyle())
        .help("Open another project")
        .accessibilityLabel("Open another project")
        .popover(isPresented: $addingProject, arrowEdge: .bottom) {
            AddProjectPopover {
                addingProject = false
            } chooseFolder: {
                choosingFolder = true
                addingProject = false
            }
            .environment(shell)
            .onDisappear {
                guard choosingFolder else { return }
                choosingFolder = false
                // The next turn of the run loop, so the sheet slides down from the window
                // instead of racing the popover's close.
                DispatchQueue.main.async {
                    FolderPicker.present { shell.addProject(at: $0) }
                }
            }
        }
    }
}

/// A project tab on the move: where it started among the open tabs and how far it went.
private struct TabDrag: Equatable {
    let name: String
    let start: Int
    let translation: Double
}

/// A flat tab: a soft fill when current, a fainter one while hovered.
private struct TabBackground: ViewModifier {
    let isCurrent: Bool
    let hovering: Bool
    /// A project tab's side padding.
    static let padding = 10.0
    /// The Pixies tab is a little roomier than a project tab.
    var padding = Self.padding
    @Environment(\.accentColors) private var accent

    func body(content: Content) -> some View {
        let shape = RoundedRectangle.rounded(Radius.row)
        content
            .padding(.horizontal, padding)
            .frame(height: TabStrip.tabHeight)
            .background(
                isCurrent ? accent.selection : hovering ? Palette.soft : .clear, in: shape
            )
            .contentShape(shape)
            .pointerStyle(.link)
    }
}

/// What follows a tab's name: in a background tab that needs the user an amber dot and
/// the count, in the current one the count alone; a running dot otherwise.
private struct TabStatus: View {
    let isCurrent: Bool
    let attention: Int
    let running: Bool

    var body: some View {
        if attention > 0 {
            if !isCurrent {
                StatusDot(tone: .waiting)
            }
            CountBadge(count: attention, urgent: true)
        } else if running {
            StatusDot(tone: .running)
        }
    }
}

/// A tab's close button, a plain grey x.
private struct TabCloseButton: View {
    let name: String
    let close: () -> Void

    var body: some View {
        Button(action: close) {
            Image(systemName: Icon.close).font(.system(size: 8, weight: .medium))
        }
        .buttonStyle(SmallSquareStyle(size: 12))
        .help("Close \(name)")
        .accessibilityLabel("Close \(name)")
    }
}

/// One project tab: its icon, name, and how many chats need the user or a running dot.
/// Every project tab has the same width (`Metrics.projectTabWidth`), a long name ending
/// in an ellipsis; in a narrow window the tabs shrink together, down to
/// `Metrics.projectTabMinWidth`. The current tab ends with its close button; a background tab shows it
/// over its end while hovered.
private struct ProjectTab: View {
    let name: String
    /// Moves the tab by this many places, for the accessibility actions.
    let move: (Int) -> Void
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        let isCurrent = shell.project == name && !shell.pixiesOpen
        let attention = shell.sessions.attention(of: name)
        let running = shell.sessions.sessions(in: name).contains {
            $0.state == .running || $0.state == .starting
        }
        let canClose = shell.app.openProjects.count > 1
        let closesOnHover = canClose && hovering && !isCurrent

        HStack(spacing: 7) {
            ProjectIcon(project: name, repo: shell.app.repo(name), size: 13)
            Text(name)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(isCurrent ? Palette.t1 : Palette.t2)
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)
            TabStatus(isCurrent: isCurrent, attention: attention, running: running)
                .fixedSize()
                .opacity(closesOnHover ? 0 : 1)
            if canClose && isCurrent {
                TabCloseButton(name: name) { shell.app.closeProject(name) }
                    .padding(.leading, 1)
            }
        }
        .frame(
            minWidth: Metrics.projectTabMinWidth - 2 * TabBackground.padding,
            maxWidth: Metrics.projectTabWidth - 2 * TabBackground.padding
        )
        .modifier(TabBackground(isCurrent: isCurrent, hovering: hovering))
        .overlay(alignment: .trailing) {
            if closesOnHover {
                TabCloseButton(name: name) { shell.app.closeProject(name) }
                    .padding(.trailing, 4)
            }
        }
        .onTapGesture { shell.selectProject(name) }
        .onHover { hovering = $0 }
        .help(attention > 0 ? "\(name), \(attention) need you" : name)
        // Ignored, not combined: a combined tab passed its press on to the close button.
        .accessibilityElement(children: .ignore)
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
        .accessibilityLabel(attention > 0 ? "\(name), \(attention) need you" : name)
        .accessibilityAction { shell.selectProject(name) }
        .accessibilityAction(named: "Close") {
            if canClose { shell.app.closeProject(name) }
        }
        .accessibilityAction(named: "Move left") { move(-1) }
        .accessibilityAction(named: "Move right") { move(1) }
    }
}

/// The leftmost tab (Cmd-0): the user's pixies, whichever project is open, styled like a
/// project tab.
private struct PixiesTab: View {
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        let isCurrent = shell.pixiesOpen
        // The pixies' pending approvals and unread reports that need action (B42).
        let attention =
            shell.approvals.pending.count { Pixie.id(ofRepo: $0.repo) != nil }
            + shell.reports.unreadActions()
        let running = shell.pixies.visible.contains { pixie in
            let state = pixie.chatSessionID.flatMap(shell.sessions.session)?.state
            return state == .running || state == .starting
        }
        let mascot = shell.shownPixie ?? shell.pixies.visible.first
        HStack(spacing: 7) {
            SpriteView(
                mascot: mascot?.mascot ?? .invader, color: mascot?.color ?? PixieColor.standard,
                size: 15)
            Text("Pixies")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(isCurrent ? Palette.t1 : Palette.t2)
                .lineLimit(1)
            TabStatus(isCurrent: isCurrent, attention: attention, running: running)
        }
        .fixedSize()
        .modifier(TabBackground(isCurrent: isCurrent, hovering: hovering, padding: 12))
        .onTapGesture { shell.openPixies() }
        .onHover { hovering = $0 }
        .help(attention > 0 ? "Pixies, \(attention) need you (⌘0)" : "Pixies (⌘0)")
        .accessibilityElement(children: .ignore)
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
        .accessibilityLabel(attention > 0 ? "Pixies, \(attention) need you" : "Pixies")
        .accessibilityAction { shell.openPixies() }
    }
}

extension ProjectIcon {
    /// A project's icon as its settings choose it; initials while the repo is unknown.
    init(project: String, repo: Repo?, size: Double = 14) {
        self.init(name: project, mascot: repo?.icon, color: repo?.iconColor, size: size)
    }
}

/// The usage chip, MonoCode's: Claude's mark, a 32 by 4 point bar for the 5-hour window
/// (amber from 80 percent used, red from 90), each window as "30% 2h 5m" (used, then the
/// time to its reset) and a refresh button. Its tooltip names each window and its reset;
/// a click opens the usage popover.
private struct UsageButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        TimelineView(.everyMinute) { context in
            let chip = UsageChip.of(usage.limits, now: context.date)
            HStack(spacing: 6) {
                Button {
                    shell.toggle(.usage)
                } label: {
                    HStack(spacing: 6) {
                        ClaudeMark(size: 12)
                        if let chip {
                            UsageBar(chip: chip)
                            entries(chip)
                        } else {
                            Text("···").foregroundStyle(Ink.content(0.35))
                        }
                    }
                }
                .buttonStyle(UsageChipStyle())
                .help(chip?.tooltip ?? "Usage details")
                .accessibilityLabel(
                    chip.map { "Claude usage: \($0.tooltip)" } ?? "Claude usage details")
                UsageRefreshButton(refreshing: usage.isRefreshing) {
                    Task { await usage.refresh() }
                }
            }
            .font(.ui(11))
            .monospacedDigit()
        }
    }

    private func entries(_ chip: UsageChip) -> some View {
        HStack(spacing: 4) {
            ForEach(Array(chip.entries.enumerated()), id: \.offset) { index, entry in
                if index > 0 {
                    Text("·").foregroundStyle(Ink.content(0.25))
                }
                Text(entry.text)
            }
        }
    }
}

/// The 32 by 4 point bar: a 10 percent track, filled to the 5-hour window's use.
private struct UsageBar: View {
    let chip: UsageChip

    var body: some View {
        Capsule()
            .fill(Ink.content(0.1))
            .frame(width: 32, height: 4)
            .overlay(alignment: .leading) {
                Capsule().fill(fill).frame(width: 32 * chip.used, height: 4)
            }
            .clipShape(Capsule())
    }

    /// Tailwind's red-400 and amber-400, as MonoCode's bar uses them.
    private var fill: Color {
        switch chip.tone {
        case .neutral: Ink.content(0.45)
        case .amber: Color(.sRGB, red: 0xFB / 255, green: 0xBF / 255, blue: 0x24 / 255)
        case .red: Color(.sRGB, red: 0xF8 / 255, green: 0x71 / 255, blue: 0x71 / 255)
        }
    }
}

/// The chip itself: 20 points tall, text at 55 percent, full strength over a 10 percent
/// fill while hovered.
private struct UsageChipStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Ink.content(hovering ? 1 : 0.55))
                .padding(.horizontal, 4)
                .frame(height: 20)
                .background(hovering ? Ink.content(0.1) : .clear, in: .rounded(4))
                .scaleEffect(configuration.isPressed ? 0.97 : 1)
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// An 18 point square with a small refresh arrow at 40 percent, turning while it refreshes.
private struct UsageRefreshButton: View {
    let refreshing: Bool
    let action: () -> Void
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            Image(systemName: Icon.refresh)
                .font(.system(size: 9, weight: .medium))
                .symbolEffect(
                    .rotate, options: .repeat(.continuous), isActive: refreshing && !reduceMotion)
        }
        .buttonStyle(UsageRefreshStyle())
        .disabled(refreshing)
        .help("Refresh usage")
        .accessibilityLabel("Refresh usage")
    }
}

private struct UsageRefreshStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Ink.content(hovering ? 1 : 0.4))
                .frame(width: 18, height: 18)
                .background(hovering ? Ink.content(0.1) : .clear, in: .rounded(4))
                .opacity(isEnabled ? 1 : 0.5)
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

private struct SearchButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.show(.palette)
        } label: {
            HStack(spacing: 7) {
                Image(systemName: Icon.search).font(.system(size: 11, weight: .regular))
                Text("Search")
                Spacer(minLength: 0)
                Text("⌘K").font(.ui(10.5))
            }
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t3)
            .padding(.horizontal, 9)
            .frame(width: 190)
        }
        .buttonStyle(StripFieldStyle())
        .accessibilityLabel("Search chats and commands")
    }
}

/// Open repos to pick from, or a folder to add.
private struct AddProjectPopover: View {
    let dismiss: () -> Void
    let chooseFolder: () -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            SectionLabel(text: "Open a project")
                .padding(.horizontal, 9)
                .padding(.bottom, 6)
            ForEach(shell.app.closedRepos) { repo in
                MenuRow(icon: nil, title: repo.name, detail: repo.path, repo: repo) {
                    shell.openProject(repo.name)
                    dismiss()
                }
            }
            if !shell.app.closedRepos.isEmpty {
                Separator().padding(.vertical, 4)
            }
            MenuRow(icon: Icon.folder, title: "Add folder…", detail: nil, action: chooseFolder)
        }
        .padding(10)
        .frame(width: 280)
    }
}

/// The folder panel, as a sheet on the window; a window of its own only when there is none.
@MainActor
enum FolderPicker {
    static func present(then open: @escaping @MainActor (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.prompt = "Open"
        panel.message = "Choose a folder to open as a project"
        guard let window = NSApp.mainWindow ?? NSApp.keyWindow else {
            if panel.runModal() == .OK, let url = panel.url {
                open(url)
            }
            return
        }
        panel.beginSheetModal(for: window) { response in
            if response == .OK, let url = panel.url {
                open(url)
            }
        }
    }
}

/// A row of a popover list.
struct MenuRow: View {
    let icon: String?
    let title: String
    let detail: String?
    /// The project a row without an icon stands for, whose icon it shows.
    var repo: Repo?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let icon {
                    Image(systemName: icon)
                        .font(.system(size: 11))
                        .foregroundStyle(Palette.t2)
                        .frame(width: 14)
                } else {
                    ProjectIcon(project: title, repo: repo, size: 14)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.ui(TypeSize.ui))
                    if let detail {
                        Text(detail)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .frame(minHeight: Metrics.rowHeight)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowHoverStyle())
    }
}

/// The strip's field-like buttons: search on a soft fill, usage bare until hovered.
struct StripFieldStyle: ButtonStyle {
    var filled = true

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .frame(height: TabStrip.tabHeight)
                .background(
                    hovering || configuration.isPressed
                        ? Palette.selection : filled ? Palette.soft : .clear,
                    in: .rounded(Radius.row)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// The strip's square icon buttons, such as add project.
struct StripIconStyle: ButtonStyle {

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(hovering ? Palette.t1 : Palette.t3)
                .frame(width: TabStrip.tabHeight, height: TabStrip.tabHeight)
                .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.row))
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// Tiny square buttons such as a tab's close button.
struct SmallSquareStyle: ButtonStyle {
    var size = 18.0

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(hovering ? Palette.t1 : Palette.t3)
                .frame(width: size, height: size)
                .background(hovering ? Palette.selection : .clear, in: .rounded(Radius.chip))
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}

/// Lets the empty parts of the strip move the window, as a title bar does.
private struct WindowDragArea: View {
    var body: some View {
        Color.clear
            .contentShape(Rectangle())
            .gesture(WindowDragGesture())
            .allowsWindowActivationEvents(true)
    }
}
