import NestKit
import SwiftUI

/// Settings > Accounts' local models (B106): each added model with where it runs and its
/// state, Start for a server that is not running, Remove in its menu; then Add local model
/// and a note on the engine local chats run on.
struct LocalModelsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.local
        SettingsSection(
            title: "\(LocalModelText.sectionTitle) · \(LocalModelText.sectionNote)", bare: true
        ) {
            if store.hasModels {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(store.models) { model in
                        LocalModelRow(model: model)
                    }
                }
                .overlay(alignment: .top) { Separator() }
            }
            Button {
                shell.openAddLocal()
            } label: {
                Label(LocalModelText.addTitle, systemImage: Icon.plus)
            }
            .buttonStyle(.nest(.soft))
            .padding(.top, store.hasModels ? 10 : 0)
            if store.hasModels {
                Text(LocalModelText.accountsNote(engine: store.engine))
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            }
        }
        .task { await store.load() }
    }
}

/// One local model: the chip mark, its name and where it runs, its state, Start while its
/// server is not running, and its menu.
private struct LocalModelRow: View {
    let model: LocalModel
    @Environment(Shell.self) private var shell
    @State private var removing = false

    var body: some View {
        let store = shell.model.local
        let state = LocalModelText.state(model)
        SettingsListRow(
            title: model.name, detail: LocalModelText.place(model), warning: model.memoryWarning
        ) {
            SettingsBadge(symbol: Icon.localModel)
        } trailing: {
            StatusLabel(tone: state.tone, label: state.text, hollow: state.tone != .review)
            if !model.running, let app = model.startApp {
                if store.starting.contains(app) {
                    Fireflies()
                }
                Button(LocalModelText.start(app)) {
                    shell.settingsChange("Could not start \(app.title)") {
                        try await store.start(app)
                    }
                }
                .buttonStyle(.nest(.soft))
                .disabled(store.starting.contains(app))
            }
            RowActionsMenu(title: model.name) {
                Button("Remove", role: .destructive) { removing = true }
            }
        }
        .help(model.weakReason ?? "")
        .confirmationDialog(
            "Remove \(model.name)?", isPresented: $removing, titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) {
                shell.settingsChange("Could not remove \(model.name)") {
                    try await store.remove(model.id)
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Chats on it keep their history; choose another model to go on with them.")
        }
    }
}

/// The Add local model sheet over the Settings window, with a scrim, as its other forms.
struct AddLocalModal: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        if let flow = shell.addLocal {
            ZStack(alignment: .top) {
                Palette.scrim
                    .ignoresSafeArea()
                    .onTapGesture { shell.addLocal = nil }
                AddLocalSheet(flow: flow).padding(.top, 36)
                Button("Close") { shell.addLocal = nil }
                    .keyboardShortcut(.cancelAction)
                    .opacity(0)
                    .frame(width: 0, height: 0)
                    .accessibilityHidden(true)
            }
        }
    }
}

/// Find on this Mac (running models to choose, downloaded ones with Start) or Enter
/// address (the address, Check, an optional key and what the check found), then Add.
struct AddLocalSheet: View {
    @Bindable var flow: AddLocalFlow
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                Text(LocalModelText.addTitle).font(.ui(TypeSize.body, .semibold))
                SegmentPicker(
                    options: [
                        (AddLocalFlow.Tab.find, LocalModelText.findTitle),
                        (.address, LocalModelText.addressTitle),
                    ],
                    selection: flow.tab
                ) { flow.tab = $0 }
                if flow.tab == .find {
                    findHeader
                } else {
                    AddressFields(flow: flow)
                }
            }
            .padding(EdgeInsets(top: 18, leading: 20, bottom: 12, trailing: 20))
            if flow.tab == .find {
                FindLists(flow: flow)
            } else {
                ForEach(flow.choices) { model in
                    FoundRow(flow: flow, model: model)
                }
            }
            HStack(spacing: 8) {
                Spacer()
                Button("Cancel") { shell.addLocal = nil }
                    .buttonStyle(.nest())
                Button(flow.addTitle) { add() }
                    .buttonStyle(.nest(.primary))
                    .disabled(!flow.canAdd)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            .overlay(alignment: .top) { Separator() }
            .padding(.top, 6)
        }
        .font(.ui(TypeSize.ui))
        .foregroundStyle(Palette.t1)
        .frame(width: 560)
        .sheetSurface()
    }

    private var findHeader: some View {
        HStack(spacing: 8) {
            Text(LocalModelText.findNote)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            if flow.finding {
                Fireflies()
            }
            Button {
                shell.settingsChange("Could not look for local models") { try await flow.find() }
            } label: {
                Label("Look again", systemImage: Icon.refresh)
            }
            .buttonStyle(.nest(.plain))
            .disabled(flow.finding)
        }
    }

    private func add() {
        let flow = flow
        shell.settingsChange("Could not add the models") {
            try await flow.add()
            shell.addLocal = nil
        }
    }
}

/// Running now, with a checkbox each, then the downloaded models with Start where Nest
/// can start their app.
private struct FindLists: View {
    let flow: AddLocalFlow
    @Environment(Shell.self) private var shell

    var body: some View {
        SheetLabel(text: LocalModelText.runningTitle)
        if flow.choices.isEmpty && flow.found != nil {
            Text(LocalModelText.nothingRunning)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 20)
                .padding(.vertical, 8)
                .overlay(alignment: .top) { Separator() }
        }
        ForEach(flow.choices) { model in
            FoundRow(flow: flow, model: model)
        }
        if let downloaded = flow.found?.downloaded, !downloaded.isEmpty {
            SheetLabel(text: LocalModelText.downloadedTitle).padding(.top, 8)
            ForEach(downloaded) { model in
                HStack(spacing: 10) {
                    SettingsCheckBox(on: false).opacity(0.4)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(model.name).foregroundStyle(Palette.t2)
                        Text(LocalModelText.downloaded(model))
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    if let app = model.start {
                        Button(LocalModelText.start(app)) {
                            shell.settingsChange("Could not start \(app.title)") {
                                try await flow.start(app)
                            }
                        }
                        .buttonStyle(.nest(.soft))
                        .disabled(flow.store.starting.contains(app))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 8)
                .overlay(alignment: .top) { Separator() }
            }
        }
    }
}

/// A small grey label over the sheet's rows.
private struct SheetLabel: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(11, .semibold))
            .foregroundStyle(Palette.t2)
            .padding(.horizontal, 20)
            .padding(.top, 4)
            .padding(.bottom, 6)
    }
}

/// A model a server offers: its checkbox, name and where it runs, a warning in the wait
/// colour when it may fail as an agent, and its tag.
private struct FoundRow: View {
    let flow: AddLocalFlow
    let model: FoundModel

    var body: some View {
        let on = flow.isSelected(model)
        Button {
            flow.toggle(model)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                SettingsCheckBox(on: on)
                    .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                    .opacity(flow.canToggle(model) ? 1 : 0.5)
                VStack(alignment: .leading, spacing: 1) {
                    Text(model.name)
                    Text(LocalModelText.place(model))
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                    ForEach(
                        [LocalModelText.warning(model), model.memoryWarning].compactMap { $0 },
                        id: \.self
                    ) { warning in
                        WarningLine(text: warning).padding(.top, 2)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if let tag = LocalModelText.tag(model) {
                    Text(tag)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(model.added ? Palette.t3 : StatusTone.review.color)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!flow.canToggle(model))
        .overlay(alignment: .top) { Separator() }
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// Where the model runs with Check, the optional key, and the line saying what answered.
private struct AddressFields: View {
    @Bindable var flow: AddLocalFlow
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(LocalModelText.addressLabel)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
            HStack(spacing: 8) {
                CardField(placeholder: "localhost:8080", text: $flow.address, submit: check)
                if flow.checking {
                    Fireflies()
                }
                Button("Check", action: check)
                    .buttonStyle(.nest(.soft))
                    .disabled(!flow.canCheck)
            }
        }
        VStack(alignment: .leading, spacing: 4) {
            Text(LocalModelText.keyLabel)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
            CardField(placeholder: "None", text: $flow.key, secure: true)
        }
        if let line = flow.checkLine {
            if line.ok {
                StatusLabel(tone: .review, label: line.text)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                SettingsFailure(text: line.text)
            }
        }
    }

    private func check() {
        let flow = flow
        shell.settingsChange("Could not check the address") { try await flow.checkAddress() }
    }
}

/// A warning in the wait colour after the warning sign, such as a model weak at tools or
/// too big for this Mac's memory (B106).
struct WarningLine: View {
    let text: String

    var body: some View {
        Label(text, systemImage: Icon.warning)
            .labelStyle(TightLabelStyle())
            .font(.ui(TypeSize.meta))
            .foregroundStyle(StatusTone.waiting.color)
            .fixedSize(horizontal: false, vertical: true)
    }
}
