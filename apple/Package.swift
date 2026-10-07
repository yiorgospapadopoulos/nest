// swift-tools-version: 6.2

import PackageDescription

let package = Package(
    name: "Harness",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "HarnessKit", targets: ["HarnessKit"]),
        .executable(name: "HarnessApp", targets: ["HarnessApp"]),
    ],
    dependencies: [
        // The terminal panes' emulator (MIT); the app target only, HarnessKit stays free of
        // dependencies. 1.12 and later compile Metal shaders, which need Xcode's separately
        // downloaded Metal Toolchain.
        .package(url: "https://github.com/migueldeicaza/SwiftTerm", exact: "1.11.0")
    ],
    targets: [
        .target(name: "HarnessKit"),
        .executableTarget(
            name: "HarnessApp",
            dependencies: ["HarnessKit", .product(name: "SwiftTerm", package: "SwiftTerm")]
        ),
        .testTarget(
            name: "HarnessKitTests",
            dependencies: ["HarnessKit"],
            resources: [.copy("Fixtures")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
