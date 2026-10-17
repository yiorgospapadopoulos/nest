#if DEBUG
    import Foundation
    import NestKit

    /// The sample daemon's artifacts (B79): a plan with three versions and a comparison
    /// page in cv-page's chats, notes from a deleted chat, and the pixies' reports.
    enum SampleArtifacts {
        static func list(now: Date) -> [Artifact] {
            let rows:
                [(
                    String, String, ArtifactKind, String, String?, String?, Bool, String?,
                    String?, Double, Int, Bool
                )] = [
                    (
                        "a-plan", "Contact form validation plan", .markdown, "cv-page", "c1",
                        "Validate contact form with zod", false, nil, nil, 4, 3, false
                    ),
                    (
                        "a-parsers", "BibTeX parsers compared", .html, "cv-page", "c2",
                        "Update publications from BibTeX", false, nil, nil, 38, 1, false
                    ),
                    (
                        "a-review", "Weekly review report", .markdown, "pixie:reviewer", "p1",
                        "Reviewer", false, "reviewer", "Reviewer", 60 * 3, 2, true
                    ),
                    (
                        "a-audit", "Lighthouse audit notes", .markdown, "cv-page", "c-gone",
                        "Run a Lighthouse audit", true, nil, nil, 60 * 26, 1, true
                    ),
                    (
                        "a-ci", "CI over the week", .html, "pixie:watcher", "p2", "Watcher",
                        false, "watcher", "Watcher", 60 * 30, 1, true
                    ),
                ]
            return rows.map {
                id, title, kind, repo, session, chat, gone, pixie, pixieName, minutes,
                versions, seen in
                Artifact(
                    id: id, title: title, kind: kind, repo: repo, sessionID: session,
                    chatTitle: chat, chatDeleted: gone, pixieID: pixie, pixieName: pixieName,
                    createdAt: now - minutes * 60 - 3600, updatedAt: now - minutes * 60,
                    latestVersion: versions, seen: seen)
            }
        }

        /// The artifact as the daemon sends it.
        static func object(_ artifact: Artifact) -> [String: Any] {
            [
                "id": artifact.id, "title": artifact.title, "kind": artifact.kind.rawValue,
                "repo": artifact.repo, "session_id": artifact.sessionID ?? NSNull(),
                "chat_title": artifact.chatTitle ?? NSNull(),
                "chat_deleted": artifact.chatDeleted, "pixie_id": artifact.pixieID ?? NSNull(),
                "pixie_name": artifact.pixieName ?? NSNull(),
                "created_at": SampleData.iso(artifact.createdAt),
                "updated_at": SampleData.iso(artifact.updatedAt),
                "latest_version": artifact.latestVersion,
                "version_count": artifact.versionCount, "seen": artifact.seen,
            ]
        }

        static func contents(now: Date) -> [String: ArtifactContent] {
            let texts: [(String, Int, ArtifactKind, String, String)] = [
                ("a-plan", 1, .markdown, "Contact form plan", plan(steps: 2)),
                ("a-plan", 2, .markdown, "Contact form validation plan", plan(steps: 3)),
                ("a-plan", 3, .markdown, "Contact form validation plan", plan(steps: 4)),
                ("a-parsers", 1, .html, "BibTeX parsers compared", parsers),
                ("a-review", 1, .markdown, "Weekly review", review),
                ("a-review", 2, .markdown, "Weekly review report", review),
                ("a-audit", 1, .markdown, "Lighthouse audit notes", audit),
                ("a-ci", 1, .html, "CI over the week", ciPage),
            ]
            let artifacts = list(now: now)
            var contents: [String: ArtifactContent] = [:]
            for (id, version, kind, title, text) in texts {
                // The latest version was saved when the artifact was last updated.
                let artifact = artifacts.first { $0.id == id }!
                contents["\(id)/\(version)"] = ArtifactContent(
                    artifactID: id, version: version, kind: kind, title: title, content: text,
                    page: kind == .markdown ? page(markdown: text, title: title) : text,
                    createdAt: artifact.updatedAt - Double(artifact.latestVersion - version) * 600)
            }
            return contents
        }

        /// A Markdown version's page, a short stand-in for the daemon's (B82): the source
        /// escaped in a `<pre>`, drawn by marked once it loads.
        private static func page(markdown: String, title: String) -> String {
            func escaped(_ text: String) -> String {
                text.replacingOccurrences(of: "&", with: "&amp;")
                    .replacingOccurrences(of: "<", with: "&lt;")
                    .replacingOccurrences(of: ">", with: "&gt;")
            }
            return """
                <!doctype html><html><head><meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>\(escaped(title))</title><style>
                :root { --bg: #ffffff; --t1: #1d1d1f; --t2: #5b5b60; --line: #e3e3e6; }
                @media (prefers-color-scheme: dark) {
                  :root { --bg: #1c1c1e; --t1: #ececee; --t2: #a1a1a8; --line: #3a3a3e; }
                }
                body { background: var(--bg); color: var(--t1); margin: 0;
                  font: 14px/1.6 -apple-system, system-ui, sans-serif; }
                main { max-width: 760px; padding: 20px 28px 28px; }
                pre { white-space: pre-wrap; font: inherit; }
                code { font: 12.5px ui-monospace, Menlo, monospace; color: var(--t2); }
                h1 { font-size: 20px; } h2 { font-size: 16px; }
                </style></head><body><main><pre id="nest-md">\(escaped(markdown))</pre></main>
                <script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
                <script>
                const source = document.getElementById("nest-md");
                if (window.marked) source.outerHTML = marked.parse(source.textContent);
                </script></body></html>
                """
        }

        private static func plan(steps: Int) -> String {
            let all = [
                "Share one zod schema between `ContactForm.tsx` and the API route.",
                "Show each field's error inline, under the field, as the user leaves it.",
                "Keep the submit button enabled; validate again on submit.",
                "Return the same messages from the route as a 422 with field names.",
            ]
            let list = all.prefix(steps).enumerated().map { "\($0.offset + 1). \($0.element)" }
            return """
                # Contact form validation

                The form accepts anything today and the route trusts it. This plan moves \
                both onto **one schema** so the rules cannot drift apart.

                ## Steps

                \(list.joined(separator: "\n"))

                ## The schema

                ```ts
                export const contact = z.object({
                  name: z.string().min(1, "Tell me your name"),
                  email: z.string().email("That email looks wrong"),
                  message: z.string().min(10, "A little more, please"),
                })
                ```

                ## Open questions

                - Should the honeypot field stay, or does the rate limit cover spam?
                - Do we keep the success toast or show the message in place?
                """
        }

        private static let review = """
            # Weekly review

            Three pull requests merged in **cv-page** this week, one is waiting.

            - #21 Dark mode polish: merged, no follow-ups.
            - #22 Publications from BibTeX: merged; the parser still logs a warning for \
            `@misc` entries.
            - #23 RSS feed: checks failed twice on the link checker, then passed.

            ## Worth a look

            The contact form still accepts empty messages. Chat *Validate contact form with \
            zod* has a plan for it.
            """

        private static let audit = """
            # Lighthouse audit

            Performance 92, accessibility 88, best practices 100, SEO 91.

            - The hero image is 1.8 MB; serve it as AVIF.
            - Two buttons have no accessible name.
            """

        private static let parsers = """
            <!doctype html>
            <html><head><title>BibTeX parsers</title><style>
            body { font: 13px -apple-system, sans-serif; margin: 24px; color: #222; }
            h1 { font-size: 18px; margin: 0 0 4px; } p { color: #666; margin: 0 0 16px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e3e3e3; }
            th { font-weight: 600; color: #555; } .yes { color: #2f8f4e; } .no { color: #c4453c; }
            @media (prefers-color-scheme: dark) {
              body { background: #1e1e1f; color: #e8e8e8; } p, th { color: #9a9a9a; }
              th, td { border-color: #333; }
            }
            </style></head><body>
            <h1>BibTeX parsers compared</h1>
            <p id="note">For the publications page, parsing at build time.</p>
            <table>
            <tr><th>Library</th><th>Size</th><th>@misc</th><th>Types</th></tr>
            <tr><td>bibtex-parse</td><td>9 kB</td><td class="yes">yes</td><td>bundled</td></tr>
            <tr><td>@retorquere/bibtex-parser</td><td>140 kB</td><td class="yes">yes</td><td>bundled</td></tr>
            <tr><td>bibtex-js</td><td>21 kB</td><td class="no">no</td><td>none</td></tr>
            </table>
            <script>document.getElementById('note').textContent += ' Sorted by size.';</script>
            </body></html>
            """

        private static let ciPage = """
            <html><body style="font: 13px -apple-system; margin: 24px">
            <h1 style="font-size: 18px">CI over the week</h1>
            <p>14 runs, 12 green.</p>
            </body></html>
            """
    }
#endif
