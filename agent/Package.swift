// swift-tools-version:5.9
// NorthLight desktop telemetry agent (PRD §5, §6).
//
// A single macOS menu-bar executable. Deliberately no dependencies: it uses
// only Apple frameworks (AppKit, IOKit, Foundation, CryptoKit), so a reviewer
// can audit every line without pulling third-party code (PRD §6: avoid
// unnecessary abstraction; §3 explainability).
import PackageDescription

let package = Package(
    name: "NorthLightAgent",
    platforms: [
        // AppKit menu-bar APIs and the IOKit idle query used here are macOS 13+.
        .macOS(.v13)
    ],
    targets: [
        .target(
            name: "NorthLightAgentCore"
        ),
        .executableTarget(
            name: "NorthLightAgent",
            dependencies: ["NorthLightAgentCore"],
            // IOKit is linked for the system idle-time query (see Telemetry.swift).
            // AppKit/Foundation/CryptoKit come in via `import` and need no linker flags.
            linkerSettings: [
                .linkedFramework("IOKit")
            ]
        ),
        .executableTarget(
            name: "NorthLightAgentCoreChecks",
            dependencies: ["NorthLightAgentCore"],
            path: "Tests/NorthLightAgentCoreChecks"
        )
    ]
)
