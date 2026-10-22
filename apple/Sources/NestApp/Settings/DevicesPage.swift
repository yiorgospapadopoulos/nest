import NestKit
import SwiftUI

/// The daemons this Mac can talk to (B105), then the devices paired with the one it talks
/// to, with Revoke, and pairing a new one with a one-time code.
struct DevicesPage: View {
    @Environment(Shell.self) private var shell
    @State private var revoking: Device?

    var body: some View {
        let devices = shell.model.devices
        DaemonsSection()
        SettingsSection(title: devices.pairedWith, bare: true) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(devices.devices) { device in
                    SettingsListRow(title: devices.title(device), detail: devices.detail(device)) {
                        SettingsBadge(symbol: device.isLocal ? Icon.laptop : Icon.phone)
                    } trailing: {
                        if devices.canRevoke(device) {
                            Button("Revoke") { revoking = device }
                                .buttonStyle(.nest(.danger))
                                .disabled(devices.revoking.contains(device.id))
                        }
                    }
                }
            }
            .overlay(alignment: .top) { Separator() }
            if let code = devices.pairingCode {
                PairingCodeView(code: code)
            } else {
                Button {
                    shell.settingsChange("Could not create a pairing code") {
                        try await devices.createPairingCode()
                    }
                } label: {
                    Label("Pair a device", systemImage: Icon.plus)
                }
                .buttonStyle(.nest(.primary))
                .disabled(devices.isCreatingCode)
                .padding(.top, 12)
            }
        }
        .task { try? await devices.load() }
        .confirmationDialog(
            "Revoke \(revoking?.name ?? "this device")?", isPresented: revokeBinding,
            titleVisibility: .visible
        ) {
            Button("Revoke", role: .destructive) {
                if let device = revoking {
                    revoke(device)
                }
            }
            Button("Cancel", role: .cancel) { revoking = nil }
        } message: {
            Text("It stops working at once and has to be paired again.")
        }
    }

    private var revokeBinding: Binding<Bool> {
        Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } })
    }

    private func revoke(_ device: Device) {
        revoking = nil
        let devices = shell.model.devices
        shell.settingsChange("Could not revoke \(device.name)") {
            try await devices.revoke(device)
            shell.show("Revoked \(device.name)", kind: .done)
        }
    }
}

/// This Mac and the paired remote daemons: the connected one says so, the others offer
/// Connect, and remotes can be removed. Then Pair a daemon.
private struct DaemonsSection: View {
    @Environment(Shell.self) private var shell
    @Environment(AppController.self) private var controller
    @State private var removing: RemoteDaemon?

    var body: some View {
        let daemons = controller.daemons
        let connected = shell.model.link.remote?.id
        SettingsSection(title: "Daemons", bare: true) {
            Text(DaemonText.daemonsNote)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.bottom, 8)
            VStack(alignment: .leading, spacing: 0) {
                SettingsListRow(
                    title: DaemonText.thisMac, detail: DaemonText.localDetail(daemons.local),
                    mono: true
                ) {
                    SettingsBadge(symbol: Icon.laptop)
                } trailing: {
                    state(connected: connected == nil) { controller.use(nil) }
                }
                ForEach(daemons.remotes) { remote in
                    SettingsListRow(
                        title: remote.machine,
                        detail: DaemonText.remoteDetail(remote, calendar: .current), mono: true
                    ) {
                        SettingsBadge(symbol: Icon.server)
                    } trailing: {
                        state(connected: connected == remote.id) { controller.use(remote.id) }
                        Button("Remove") { removing = remote }
                            .buttonStyle(.nest(.danger))
                    }
                }
            }
            .overlay(alignment: .top) { Separator() }
            Button {
                controller.beginPairing()
            } label: {
                Label("Pair a daemon", systemImage: Icon.plus)
            }
            .buttonStyle(.nest(.soft))
            .padding(.top, 12)
        }
        .confirmationDialog(
            "Remove \(removing?.machine ?? "this daemon")?",
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            titleVisibility: .visible, presenting: removing
        ) { remote in
            Button("Remove", role: .destructive) { controller.remove(remote.id) }
            Button("Cancel", role: .cancel) {}
        } message: { remote in
            Text(DaemonText.removeMessage(remote.machine))
        }
    }

    @ViewBuilder
    private func state(connected: Bool, connect: @escaping () -> Void) -> some View {
        if connected {
            StatusLabel(tone: .review, label: "Connected")
        } else {
            Button("Connect", action: connect).buttonStyle(.nest(.soft))
        }
    }
}

/// Pair a daemon, over the Settings window with a scrim like its other sheets.
struct PairDaemonModal: View {
    @Environment(AppController.self) private var controller

    var body: some View {
        if let pairing = controller.pairing {
            ZStack {
                Palette.scrim
                    .ignoresSafeArea()
                    .onTapGesture { controller.pairing = nil }
                PairDaemonSheet(pairing: pairing).padding(40)
            }
        }
    }
}

/// The address, the code and this Mac's name there; the found machine and errors show in
/// place.
private struct PairDaemonSheet: View {
    @Bindable var pairing: DaemonPairing
    @Environment(AppController.self) private var controller

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Pair with a daemon on another machine").font(.ui(TypeSize.body, .semibold))
            Text(
                LocalizedStringKey(
                    "On that machine, open Nest's Settings > Devices > Pair a device, or run"
                        + " `nestd pair` in Terminal. Its address is the name"
                        + " `tailscale serve` gives it.")
            )
            .foregroundStyle(Palette.t2)
            .fixedSize(horizontal: false, vertical: true)
            FormLine(label: "Address") {
                CardField(
                    placeholder: "mac-mini.tail1a2b.ts.net", text: $pairing.address,
                    submit: { Task { await pairing.check() } }
                )
                .font(.mono(TypeSize.meta))
            }
            FormLine(label: "Pairing code") {
                CardField(placeholder: "K7QMR4XP", text: $pairing.code)
                    .font(.mono(TypeSize.reading))
                    .frame(width: 160)
            }
            FormLine(label: "Name for this Mac there") {
                CardField(placeholder: "MacBook Air", text: $pairing.deviceName)
            }
            if let error = pairing.error {
                Label(error, systemImage: Icon.warning)
                    .labelStyle(TightLabelStyle())
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
            } else if let found = pairing.foundText {
                StatusLabel(tone: .review, label: found)
            }
            HStack(spacing: 8) {
                if pairing.isBusy {
                    Fireflies()
                }
                Spacer()
                Button("Cancel") { controller.pairing = nil }
                    .buttonStyle(.nest())
                    .keyboardShortcut(.cancelAction)
                Button("Pair and connect") { controller.pair() }
                    .buttonStyle(.nest(.primary))
                    .disabled(!pairing.canPair)
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.top, 6)
        }
        .font(.ui(TypeSize.ui))
        .foregroundStyle(Palette.t1)
        .padding(20)
        .frame(width: 500)
        .sheetSurface()
    }
}

/// The one-time code, large, with its countdown and where to enter it.
private struct PairingCodeView: View {
    let code: PairingCode
    @Environment(Shell.self) private var shell

    var body: some View {
        let devices = shell.model.devices
        VStack(spacing: 8) {
            Text(code.code)
                .font(.mono(24, .semibold))
                .tracking(6)
                .textSelection(.enabled)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(devices.expiryText(at: context.date))
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
                    .foregroundStyle(
                        devices.secondsLeft(at: context.date) > 0
                            ? Palette.t3 : StatusTone.failed.color)
            }
            Text("Open your tailnet address in Safari on the iPhone, then enter this code.")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .multilineTextAlignment(.center)
            HStack(spacing: 6) {
                Button("New code") {
                    Task { try? await devices.createPairingCode() }
                }
                .buttonStyle(.nest(.plain))
                Button("Done") { devices.clearPairingCode() }
                    .buttonStyle(.nest(.soft))
            }
            .padding(.top, 2)
        }
        .frame(maxWidth: .infinity)
        .padding(14)
        .softFill(radius: 8)
        .padding(.top, 12)
    }
}
