import NestComputerCore
import Testing

@Suite struct KeyTableTests {
    @Test func everyKeyTheProtocolNamesHasItsCode() {
        let letters = "abcdefghijklmnopqrstuvwxyz".map(String.init)
        let digits = "0123456789".map(String.init)
        let names =
            ["return", "tab", "escape", "delete", "up", "down", "left", "right", "space"]
            + letters + digits
        #expect(Set(KeyCodes.table.keys) == Set(names))
        #expect(Set(KeyCodes.table.values).count == names.count)
    }

    @Test func codesMatchTheANSIKeyboard() {
        let expected: [String: UInt16] = [
            "return": 36, "tab": 48, "escape": 53, "delete": 51, "space": 49, "left": 123,
            "up": 126, "a": 0, "s": 1, "z": 6, "c": 8, "v": 9, "q": 12, "w": 13, "m": 46,
            "0": 29, "1": 18, "9": 25,
        ]
        for (name, code) in expected { #expect(KeyCodes.code(for: name) == code, "\(name)") }
        #expect(KeyCodes.code(for: "Return") == 36)
    }

    @Test func modifiersMapToEventFlags() {
        #expect(Modifier.flags([.cmd]) == 0x0010_0000)
        #expect(Modifier.flags([.shift, .option, .control]) == 0x000E_0000)
    }
}

@Suite struct ScalingTests {
    @Test func screenshotsAreScaledToTheLongSide() {
        #expect(fittedSize(width: 2560, height: 1600) == (1280, 800))
        #expect(fittedSize(width: 1000, height: 3000) == (427, 1280))
        #expect(fittedSize(width: 800, height: 600) == (800, 600))
    }

    @Test func clicksStayInsideTheWindow() throws {
        let window = Rect(x: 100, y: 200, width: 400, height: 300)
        let point = try screenPoint(in: window, x: 10, y: 20)
        #expect(point == (110, 220))
        #expect(throws: HelperError.self) { try screenPoint(in: window, x: 400, y: 10) }
        #expect(throws: HelperError.self) { try screenPoint(in: window, x: -1, y: 10) }
    }
}

@Suite struct LaunchOptionsTests {
    @Test func theSocketAndControllerAreRead() throws {
        let options = try LaunchOptions(arguments: [
            "-psn_0_123", "--socket", "/tmp/nest.sock", "--controller", "4321",
        ])
        #expect(options.socket == "/tmp/nest.sock")
        #expect(options.controller == 4321)
    }

    @Test func missingOrUnusableArgumentsStopTheLaunch() {
        #expect(throws: HelperError.self) { try LaunchOptions(arguments: ["--controller", "9"]) }
        #expect(throws: HelperError.self) {
            try LaunchOptions(arguments: ["--socket", "/tmp/a.sock", "--controller", "x"])
        }
        let long = "/" + String(repeating: "a", count: LaunchOptions.maxSocketPathBytes)
        #expect(throws: HelperError.self) {
            try LaunchOptions(arguments: ["--socket", long, "--controller", "9"])
        }
    }
}

@Suite struct ChromiumTests {
    @Test func chromiumAndElectronAppsAreRecognisedByTheirFramework() {
        #expect(
            Roles.isChromium(frameworks: ["Sparkle.framework", "Electron Framework.framework"]))
        #expect(Roles.isChromium(frameworks: ["Google Chrome Framework.framework"]))
        #expect(!Roles.isChromium(frameworks: ["Sparkle.framework", "libswiftCore.dylib"]))
    }
}
