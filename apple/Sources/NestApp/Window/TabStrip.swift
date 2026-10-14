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

    @Environment(Shell.self) private var shell
    @State private var addingProject = false
    /// Add folder was picked: the panel opens once the popover has gone.
    @State private var choosingFolder = false

    var body: some View {
        HStack(spacing: 2) {
            PixiesTab()
            Rectangle()
                .fill(Palette.divider)
                .frame(width: 1, height: 16)
                .padding(.horizontal, 6)
                .accessibilityHidden(true)
            ForEach(shell.app.openProjects, id: \.self) { name in
                ProjectTab(name: name)
            }
            addButton
            Spacer(minLength: 12)
            UsageButton().padding(.trailing, 6)
            SearchButton()
        }
        .padding(.leading, fullScreen ? Self.fullScreenInset : Self.leadingInset)
        .padding(.trailing, 10)
        .frame(height: Metrics.stripHeight)
        .background(WindowDragArea())
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

/// A flat tab sized to its content: a soft fill when current, a fainter one while hovered.
private struct TabBackground: ViewModifier {
    let isCurrent: Bool
    let hovering: Bool
    /// The Pixies tab is a little roomier than a project tab.
    var padding = 10.0
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
/// The current tab ends with its close button; a background tab shows it over its end
/// while hovered, so no tab changes width.
private struct ProjectTab: View {
    let name: String
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
            TabStatus(isCurrent: isCurrent, attention: attention, running: running)
                .opacity(closesOnHover ? 0 : 1)
            if canClose && isCurrent {
                TabCloseButton(name: name) { shell.app.closeProject(name) }
                    .padding(.leading, 1)
            }
        }
        .fixedSize()
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
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
        .accessibilityLabel(attention > 0 ? "\(name), \(attention) need you" : name)
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

/// The usage chip, the approved design's: Claude's mark, a 32 by 4 point bar for the 5-hour window
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

    /// Tailwind's red-400 and amber-400, as the approved design's bar uses them.
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
