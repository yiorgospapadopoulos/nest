import Foundation
import Testing

@testable import NestKit

@Suite("File references")
struct FileReferenceTests {
    private func paths(_ text: String) -> [String] {
        let units = Array(text.utf16)
        return FileReference.inText(text).map {
            String(decoding: units[$0.start..<$0.end], as: UTF16.self)
        }
    }

    @Test("paths in plain text are found with their line, on real shapes")
    func plainText() {
        #expect(
            paths("Fixed in web/src/App.tsx:42 and index.html:111.") == [
                "web/src/App.tsx:42", "index.html:111",
            ])
        #expect(
            paths("See (plans/handoff.md), `x` README.md, or ../a/b.ts:1:2.") == [
                "plans/handoff.md", "README.md", "../a/b.ts:1:2",
            ])
        #expect(
            paths("/Users/me/nest/design/tokens.toml:3-9 and .claude/settings.json") == [
                "/Users/me/nest/design/tokens.toml:3-9", ".claude/settings.json",
            ])
        #expect(FileReference.inText("see a/b.md:12.").first?.path == "a/b.md")
    }

    @Test("URLs, versions, domains and identifiers stay text")
    func notFiles() {
        for text in [
            "https://example.com/a.md", "ssh://host/x/y.md", "git@github.com:o/r.git",
            "version 1.2.3 or v2.0.1", "example.com and www.example.com/docs/a.md",
            "console.log(a.b) with obj.field and e.g. this", "Node.js and Next.js",
            "HTTP/1.1, 1/2.5, TCP/IP, and/or, text/plain", "a call: file.py()",
            "src/*.ts and **/x.ts and ~/notes/a.md and $HOME/a.md", "web/src/ the folder",
        ] {
            #expect(paths(text) == [], "\(text)")
        }
    }

    @Test("a whole code span is a path or nothing")
    func codeSpans() {
        #expect(FileReference.inCode("index.html:111") == "index.html")
        #expect(FileReference.inCode("web/src/App.tsx:42") == "web/src/App.tsx")
        #expect(FileReference.inCode("app/(shop)/[id]/page.tsx") == "app/(shop)/[id]/page.tsx")
        for code in [
            "git diff web/App.tsx", "https://a.b/c.md", "1.2.3", "foo.bar", "src/*.ts", "a/b",
            "${HOME}/x.md",
        ] {
            #expect(FileReference.inCode(code) == nil, "\(code)")
        }
    }

    @Test("a markdown link with no scheme is a file")
    func links() {
        #expect(FileReference.inLink("plans/project-plan.md") == "plans/project-plan.md")
        #expect(FileReference.inLink("./a.ts#L12") == "./a.ts")
        #expect(FileReference.inLink("web/src/App.tsx:42") == "web/src/App.tsx")
        #expect(FileReference.inLink("index.html:111") == "index.html")
        #expect(FileReference.inLink("/Users/me/nest/README.md") == "/Users/me/nest/README.md")
        #expect(FileReference.inLink("LICENSE") == "LICENSE")
        #expect(FileReference.inLink("my%20notes/a.md") == "my notes/a.md")
        #expect(FileReference.inLink("../../etc/passwd") == "../../etc/passwd")
        for url in [
            "https://example.com/a.md", "file:///etc/passwd", "javascript:alert(1)",
            "mailto:me@example.com", "#section", "//example.com/a.md", "example.com",
            "www.example.org/x", "docs/", "..", "%zz", "a%0Ab.md",
        ] {
            #expect(FileReference.inLink(url) == nil, "\(url)")
        }
    }

    @Test("messages carry files as runs, and no message can make a file a web link")
    func runs() {
        let runs = RichText.paragraphs(
            "See [the plan](plans/plan.md), `web/App.tsx:42`, [i](index.html:111) and a/b.md."
        )[0].runs
        #expect(
            runs.compactMap(\.file) == ["plans/plan.md", "web/App.tsx", "index.html", "a/b.md"])
        #expect(runs.map(\.text).joined() == "See the plan, web/App.tsx:42, i and a/b.md.")
        #expect(runs.allSatisfy { $0.link == nil })

        let safe = RichText.paragraphs("[w](https://a.b/c.md) [no](file:///etc/passwd)")[0].runs
        #expect(safe.compactMap(\.file) == [])
        #expect(safe.compactMap(\.link).map(\.absoluteString) == ["https://a.b/c.md"])
    }

    @Suite("opening")
    struct Opening {
        private func tree() throws -> (top: URL, folder: String) {
            let manager = FileManager.default
            let top = manager.temporaryDirectory.appending(path: UUID().uuidString)
            let project = top.appending(path: "project")
            let outside = top.appending(path: "outside")
            try manager.createDirectory(
                at: project.appending(path: "docs"), withIntermediateDirectories: true)
            try manager.createDirectory(at: outside, withIntermediateDirectories: true)
            try Data().write(to: project.appending(path: "docs/plan.md"))
            try Data().write(to: project.appending(path: "run.command"))
            try Data().write(to: outside.appending(path: "key.md"))
            try manager.createSymbolicLink(
                at: project.appending(path: "key.md"),
                withDestinationURL: outside.appending(path: "key.md"))
            try manager.createSymbolicLink(
                at: project.appending(path: "away"), withDestinationURL: outside)
            try manager.createSymbolicLink(
                at: project.appending(path: "near.md"),
                withDestinationURL: project.appending(path: "docs/plan.md"))
            return (top, project.path)
        }

        @Test("a regular file inside the chat's folder resolves to its real path")
        func allowed() throws {
            let (top, folder) = try tree()
            defer { try? FileManager.default.removeItem(at: top) }
            let plan = try #require(FileReference.resolve("docs/plan.md", in: folder))
            #expect(plan.hasSuffix("/project/docs/plan.md"))
            #expect(FileReference.resolve("./docs/../docs/plan.md", in: folder) == plan)
            #expect(FileReference.resolve(plan, in: folder) == plan)
            #expect(FileReference.resolve(folder + "/docs/plan.md", in: folder) == plan)
            #expect(FileReference.resolve("near.md", in: folder) == plan)
        }

        @Test("escapes, links out, folders and missing files are refused")
        func refused() throws {
            let (top, folder) = try tree()
            defer { try? FileManager.default.removeItem(at: top) }
            for path in [
                "../outside/key.md", "docs/../../outside/key.md", "key.md", "away/key.md",
                top.path + "/outside/key.md", "/etc/passwd", "docs", ".", "missing.md",
            ] {
                #expect(FileReference.resolve(path, in: folder) == nil, "\(path)")
            }
            #expect(FileReference.resolve("docs/plan.md", in: "project") == nil)
            #expect(FileReference.resolve("docs/plan.md", in: folder + "/gone") == nil)
            #expect(FileReference.resolve("/etc/passwd", in: "/") == nil)
        }
    }
}
