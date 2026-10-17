import NestKit
import SwiftUI

/// Paired devices with Revoke, and pairing a new one with a one-time code.
struct DevicesPage: View {
    @Environment(Shell.self) private var shell
    @State private var revoking: Device?

    var body: some View {
        let devices = shell.model.devices
        SettingsSection(title: "", bare: true) {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(devices.devices) { device in
                    SettingsListRow(
                        title: device.name,
                        detail: device.isLocal ? "This Mac" : devices.lastSeenText(device)
                    ) {
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
