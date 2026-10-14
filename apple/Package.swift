// swift-tools-version: 6.2

import PackageDescription

let package = Package(
    name: "Nest",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "NestKit", targets: ["NestKit"]),
        .executable(name: "NestApp", targets: ["NestApp"]),
    ],
    dependencies: [
        // The terminal panes' emulator (MIT); the app target only, NestKit stays free of
        // dependencies. 1.12 and later compile Metal shaders, which need Xcode's separately
        // downloaded Metal Toolchain.
        .package(url: "https://github.com/migueldeicaza/SwiftTerm", exact: "1.11.0")
    ],
    targets: [
        .target(name: "NestKit"),
        .executableTarget(
            name: "NestApp",
            dependencies: ["NestKit", .product(name: "SwiftTerm", package: "SwiftTerm")]
        ),
        .testTarget(
            name: "NestKitTests",
            dependencies: ["NestKit"],
            resources: [.copy("Fixtures")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
