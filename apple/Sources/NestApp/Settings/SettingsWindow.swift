import AppKit
import NestKit
import SwiftUI

/// The Settings window (B81): a category sidebar with a search field and the projects,
/// and the chosen page beside it.
struct SettingsWindow: View {
    static let id = "settings"

    @Environment(AppController.self) private var controller

    var body: some View {
        Group {
            if let shell = controller.shell {
                SettingsView().environment(shell)
            } else {
                Text("Nest is starting")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Palette.windowOpaque)
            }
        }
        .frame(minWidth: 760, minHeight: 520)
    }
}

/// The sidebar and the page, in the app's accent and mode.
struct SettingsView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.settings
        HStack(spacing: 0) {
            SettingsSidebar()
                .frame(width: 216)
                .background(Palette.side)
            Separator(axis: .vertical)
            SettingsDetail()
        }
        .background(Palette.windowOpaque)
        .ignoresSafeArea()
        .overlay(alignment: .top) {
            if let toast = shell.toast {
                ToastView(toast: toast)
                    .padding(.top, 14)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .foregroundStyle(Palette.t1)
        .environment(\.accentColors, AccentColors(accent: settings.accent))
        .preferredColorScheme(settings.theme.colorScheme)
    }
}

extension ThemeMode {
    var colorScheme: ColorScheme? {
        switch self {
        case .auto: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

extension SettingsPage {
    /// The sidebar's and header's symbol for a page that is not a project.
    var symbol: String {
        switch self {
        case .general: "gearshape"
        case .appearance: "circle.lefthalf.filled"
        case .notifications: "bell"
        case .agents: "cpu"
        case .pixies: "face.smiling"
        case .accounts: "person.crop.circle"
        case .extensions: "puzzlepiece.extension"
        case .devices: "laptopcomputer.and.iphone"
        case .shortcuts: "keyboard"
        case .project: "folder"
        case .addProject: "plus"
        }
    }
}

/// A page's icon: a project's own, else its symbol.
struct SettingsPageIcon: View {
    let page: SettingsPage
    var size = 14.0
    @Environment(Shell.self) private var shell

    var body: some View {
        if case .project(let name) = page {
            ProjectIcon(project: name, repo: shell.app.repo(name), size: size + 2)
        } else {
            Image(systemName: page.symbol)
                .font(.system(size: size - 2))
                .foregroundStyle(Palette.t2)
                .frame(width: size + 2, height: size + 2)
        }
    }
}

private struct SettingsSidebar: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        @Bindable var shell = shell
        let listed = SettingsPage.listed(
            projects: shell.app.repos.map(\.name), query: shell.settingsQuery)
        VStack(alignment: .leading, spacing: 0) {
            SearchField(text: $shell.settingsQuery)
                .padding(.horizontal, 10)
                .padding(.top, 40)
                .padding(.bottom, 8)
            ScrollView {
                VStack(alignment: .leading, spacing: 1) {
                    ForEach(listed.pages, id: \.self) { page in
                        SidebarItem(page: page)
                    }
                    if !listed.projects.isEmpty {
                        Text("Projects")
                            .font(.ui(10.5, .medium))
                            .foregroundStyle(Palette.t3)
                            .padding(.horizontal, 8)
                            .padding(.top, 12)
                            .padding(.bottom, 4)
                        ForEach(listed.projects, id: \.self) { page in
                            SidebarItem(page: page)
                        }
                    }
                    if listed.pages.isEmpty && listed.projects.isEmpty {
                        Text("No matches")
                            .font(.ui(10.5, .medium))
                            .foregroundStyle(Palette.t3)
                            .padding(8)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 8)
            }
            .scrollIndicators(.never)
            Separator()
            ServiceFooter()
        }
    }
}

private struct SearchField: View {
    @Binding var text: String

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: Icon.search)
                .font(.system(size: 10.5))
                .foregroundStyle(Palette.t3)
            TextField("", text: $text)
                .textFieldStyle(.plain)
                .font(.ui(TypeSize.ui))
                .overlay(alignment: .leading) {
                    Placeholder(text: "Search settings", shown: text.isEmpty)
                        .font(.ui(TypeSize.ui))
                }
                .accessibilityLabel("Search settings")
        }
        .padding(.horizontal, 8)
        .frame(height: 26)
        .background(Palette.soft, in: .rounded(7))
    }
}

private struct SidebarItem: View {
    let page: SettingsPage
    @Environment(Shell.self) private var shell

    var body: some View {
        let selected = shell.settingsPage == page
        Button {
            shell.openSettings(page)
        } label: {
            HStack(spacing: 8) {
                SettingsPageIcon(page: page)
                Text(page.title)
                    .font(.ui(TypeSize.ui))
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 8)
            .frame(height: 26)
            .contentShape(Rectangle())
            .listRow(selected: selected, radius: 6)
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// Whether the Nest service answers.
private struct ServiceFooter: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let connected = shell.app.connection == .connected
        HStack(spacing: 8) {
            StatusDot(tone: connected ? .review : .waiting, size: 7)
            Text(connected ? "Nest service running" : "Nest service not connected")
                .lineLimit(1)
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t2)
        .padding(.horizontal, 14)
        .frame(height: 38)
    }
}

/// The page's sticky header and its scrolling body, up to 720 points wide.
private struct SettingsDetail: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let page = currentPage
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                SettingsPageIcon(page: page, size: 16)
                VStack(alignment: .leading, spacing: 1) {
                    Text(page.title).font(.ui(15, .semibold))
                    if case .project(let name) = page, let repo = shell.app.repo(name) {
                        Text(repo.path)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(Palette.t2)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 28)
            .padding(.top, 18)
            .padding(.bottom, 12)
            .overlay(alignment: .bottom) { Separator() }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    pageBody(page)
                }
                .frame(maxWidth: 720, alignment: .leading)
                .padding(.horizontal, 28)
                .padding(.top, 6)
                .padding(.bottom, 40)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollIndicators(.automatic)
            .id(page)
        }
    }

    /// A removed project's page falls back to General.
    private var currentPage: SettingsPage {
        if case .project(let name) = shell.settingsPage, shell.app.repo(name) == nil {
            return .general
        }
        return shell.settingsPage
    }

    @ViewBuilder private func pageBody(_ page: SettingsPage) -> some View {
        switch page {
        case .general: GeneralPage()
        case .appearance: AppearancePage()
        case .notifications: NotificationsPage()
        case .agents: AgentsPage()
        case .pixies: PixiesPage()
        case .accounts: AccountsPage()
        case .extensions: ExtensionsPage()
        case .devices: DevicesPage()
        case .shortcuts: ShortcutsPage()
        case .project(let name): ProjectPage(project: name)
        case .addProject: AddProjectPage()
        }
    }
}

// MARK: Rows

/// A small grey section title over its rows; rows are separated by thin lines.
struct SettingsSection<Content: View>: View {
    let title: String
    /// Rows draw their own lines; other content, such as a list, goes in bare.
    var bare = false
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if !title.isEmpty {
                Text(title)
                    .font(.ui(11, .semibold))
                    .foregroundStyle(Palette.t2)
                    .padding(.bottom, 6)
            }
            if bare {
                content()
            } else {
                VStack(alignment: .leading, spacing: 0) { content() }
                    .overlay(alignment: .top) { Separator() }
            }
        }
        .padding(.top, 18)
    }
}

/// A label on the left and its control on the right, over a thin line.
struct SettingsRow<Control: View>: View {
    let label: String
    @ViewBuilder let control: () -> Control

    var body: some View {
        HStack(spacing: 16) {
            Text(label)
                .font(.ui(TypeSize.ui, .medium))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            HStack(spacing: 6) { control() }
        }
        .padding(.vertical, 7)
        .frame(minHeight: 36)
        .overlay(alignment: .bottom) { Separator() }
    }
}

/// A list row: an icon, a title with an optional line under it, and its controls.
struct SettingsListRow<Leading: View, Trailing: View>: View {
    let title: String
    var detail: String?
    var mono = false
    @ViewBuilder let leading: () -> Leading
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        HStack(spacing: 10) {
            leading()
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.ui(TypeSize.ui, .medium)).lineLimit(1)
                if let detail {
                    Text(detail)
                        .font(mono ? .mono(TypeSize.meta) : .ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(2)
                        .truncationMode(.middle)
                }
            }
            Spacer(minLength: 8)
            HStack(spacing: 6) { trailing() }
        }
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) { Separator() }
    }
}

/// A list's square badge: a letter or two, or a symbol.
struct SettingsBadge: View {
    var text: String?
    var symbol: String?

    var body: some View {
        Group {
            if let symbol {
                Image(systemName: symbol).font(.system(size: 11))
            } else {
                Text(text ?? "").font(.ui(10.5, .semibold))
            }
        }
        .foregroundStyle(Palette.t2)
        .frame(width: 26, height: 26)
        .background(Palette.soft, in: .rounded(6))
    }
}

/// Text in the secondary colour beside a control, in mono for paths and addresses.
struct SettingsValue: View {
    let text: String
    var mono = false

    var body: some View {
        Text(text)
            .font(mono ? .mono(TypeSize.meta) : .ui(TypeSize.ui))
            .foregroundStyle(Palette.t2)
            .lineLimit(1)
            .truncationMode(.middle)
            .textSelection(.enabled)
    }
}

/// Small underlined tabs, such as a project page's.
struct SettingsTabs<Tab: Hashable>: View {
    let tabs: [(Tab, String)]
    let selection: Tab
    let select: (Tab) -> Void

    var body: some View {
        HStack(spacing: 4) {
            ForEach(tabs, id: \.0) { tab, title in
                let on = tab == selection
                Button {
                    select(tab)
                } label: {
                    Text(title)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(on ? Palette.t1 : Palette.t2)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 7)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(on ? Palette.t1 : .clear).frame(height: 2)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
            Spacer(minLength: 0)
        }
        .overlay(alignment: .bottom) { Separator() }
        .padding(.top, 8)
        .padding(.bottom, 4)
    }
}

/// A short failure line under a control.
struct SettingsFailure: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(StatusTone.failed.color)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 6)
    }
}

extension Shell {
    /// Runs a settings change, saying in a toast when it fails.
    func settingsChange(_ failure: String, _ action: @escaping @MainActor () async throws -> Void) {
        Task {
            do {
                try await action()
            } catch {
                show(error, doing: failure)
            }
        }
    }
}
