import Foundation
import Testing

@testable import NestKit

/// B79: artifacts the chats save, their events, how they read, the store behind the
/// Artifacts view and the badge, and their cards and tool calls in a transcript.
@MainActor @Suite struct ArtifactsTests {
    let api = FakeAPI()

    func store(_ artifacts: [Artifact] = [], unseen: Int = 0) -> ArtifactsStore {
        api.set {
            $0.artifacts = artifacts
            $0.unseenArtifacts = unseen
        }
        return ArtifactsStore(api: api)
    }

    static func savedEvent(_ artifact: String, version: Int = 1, unseen: Int = 1) -> Event {
        Fixture.event(
            EventType.artifactSaved,
            #"{"artifact": \#(artifact), "action": "updated", "version": \#(version), "unseen": \#(unseen)}"#,
            session: nil)
    }

    // MARK: Models and events

    @Test func anArtifactDecodesEveryField() {
        let artifact = Fixture.artifact(
            kind: "html", pixie: "p1", pixieName: "Reviewer", seen: true)
        #expect(artifact.id == "a1")
        #expect(artifact.title == "Options compared")
        #expect(artifact.kind == .html)
        #expect(artifact.repo == "cv-page")
        #expect(artifact.sessionID == "s1")
        #expect(artifact.chatTitle == "Pick a queue")
        #expect(!artifact.chatDeleted)
        #expect(artifact.pixieID == "p1")
        #expect(artifact.pixieName == "Reviewer")
        #expect(artifact.createdAt == Fixture.date("2026-10-17T09:30:00Z"))
        #expect(artifact.updatedAt == Fixture.date("2026-10-17T09:42:10Z"))
        #expect(artifact.latestVersion == 3)
        #expect(artifact.versionCount == 3)
        #expect(artifact.seen)
        #expect(Fixture.artifact(kind: "pdf").kind == .unknown)
        #expect(
            ["markdown", "html", "slides", "document", "design", "design_system"].map {
                Fixture.artifact(kind: $0).kind
            } == [.markdown, .html, .slides, .document, .design, .designSystem])
        let made = Artifact(
            id: "a1", title: "Options compared", kind: .html, repo: "cv-page", sessionID: "s1",
            chatTitle: "Pick a queue", pixieID: "p1", pixieName: "Reviewer",
            createdAt: artifact.createdAt, updatedAt: artifact.updatedAt, latestVersion: 3,
            seen: true)
        #expect(made == artifact)
    }

    @Test func aDetailCarriesItsVersionsOldestFirst() {
        let detail = Fixture.detail(Fixture.artifact(latest: 2))
        #expect(detail.artifact.id == "a1")
        #expect(detail.versions.map(\.version) == [1, 2])
        #expect(detail.versions[0].title == "Options compared")
        #expect(detail.versions[0].size == 10)
        #expect(detail.versions[0].createdAt == Fixture.date("2026-10-17T09:30:00Z"))
        #expect(detail.versions[0].author == .agent)
    }

    @Test func versionsSayWhoMadeThem() {
        func version(_ author: String?) -> ArtifactVersion {
            let field = author.map { #", "author": "\#($0)""# } ?? ""
            return Fixture.decode(
                ArtifactVersion.self,
                json:
                    #"{"version": 4, "title": "Plan", "size": 7, "created_at": "2026-10-17T09:30:00+00:00"\#(field)}"#
            )
        }
        #expect(version("user").author == .user)
        #expect(version("agent").author == .agent)
        #expect(version("robot").author == .unknown)
        // A daemon from before B88 sends no author: those were all the agent's.
        #expect(version(nil).author == .agent)
        let made = ArtifactVersion(
            version: 4, title: "Plan", size: 7, createdAt: Fixture.date("2026-10-17T09:30:00Z"),
            author: .user)
        #expect(made == version("user"))
        #expect(
            ArtifactVersion(version: 1, title: "T", size: 0, createdAt: made.createdAt).author
                == .agent)
    }

    @Test func versionContentDecodesAndMeasuresItsBytes() {
        let decoded = Fixture.decode(ArtifactContent.self, json: RouteCase.contentJSON)
        #expect(decoded.artifactID == "a1")
        #expect(decoded.version == 2)
        #expect(decoded.kind == .html)
        #expect(decoded.title == "Options compared")
        #expect(decoded.content == "<p>Hi</p>")
        #expect(decoded.page == "<!doctype html><p>Hi</p>")
        #expect(decoded.size == 9)
        #expect(decoded.createdAt == Fixture.date("2026-10-17T09:41:00Z"))
        #expect(Fixture.content("a1", 1, "é").size == 2)
        #expect(decoded.author == .agent)
        let edited = Fixture.decode(
            ArtifactContent.self,
            json: String(RouteCase.contentJSON.dropLast()) + #", "author": "user"}"#)
        #expect(edited.author == .user)
        #expect(edited.content == "<p>Hi</p>")
        #expect(Fixture.content("a1", 1).author == .agent)
    }

    @Test func artifactEventsDecode() {
        let card = Fixture.event(
            EventType.sessionArtifact,
            #"{"artifact_id": "a1", "version": 2, "title": "Options", "kind": "html", "action": "updated"}"#
        )
        guard case .sessionArtifact(let body) = card.body else {
            Issue.record("not a card: \(card.body)")
            return
        }
        #expect(body.artifactID == "a1")
        #expect(body.version == 2)
        #expect(body.title == "Options")
        #expect(body.kind == .html)
        #expect(body.action == .updated)

        guard case .artifactSaved(let saved) = Self.savedEvent(Fixture.artifactJSON()).body else {
            Issue.record("not saved")
            return
        }
        #expect(saved.artifact == Fixture.artifact())
        #expect(saved.action == .updated)
        #expect(saved.version == 1)
        #expect(saved.unseen == 1)

        let seen = Fixture.event(
            EventType.artifactSeen, #"{"artifact_id": "a1", "unseen": 2}"#, session: nil)
        #expect(seen.body == .artifactSeen(id: "a1", unseen: 2))
        let gone = Fixture.event(
            EventType.artifactDeleted, #"{"artifact_id": "a1", "unseen": 0}"#, session: nil)
        #expect(gone.body == .artifactDeleted(id: "a1", unseen: 0))
    }

    // MARK: How they read

    @Test func theCSPGoesAheadOfEveryElement() {
        let meta = ArtifactHTML.meta
        #expect(
            meta
                == #"<meta http-equiv="Content-Security-Policy" content="\#(ArtifactHTML.policy)">"#
        )
        // B82: the same policy as the iPhone's frame, word for word.
        #expect(
            ArtifactHTML.policy
                == "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/ https://unpkg.com https://cdn.tailwindcss.com https://code.jquery.com; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; worker-src 'none'"
        )
        #expect(
            ArtifactHTML.sandboxed("<html><head><title>T</title></head></html>")
                == meta + "<html><head><title>T</title></head></html>")
        #expect(
            ArtifactHTML.sandboxed("\u{FEFF}<!DOCTYPE html>\n<!-- made by Claude -->\n<html>")
                == "\u{FEFF}<!DOCTYPE html>\n<!-- made by Claude -->\n" + meta + "<html>")
        // A comment or tag that mentions a head cannot hide the policy.
        #expect(
            ArtifactHTML.sandboxed("<!-- <head> --><p>Hi</p>")
                == "<!-- <head> -->" + meta + "<p>Hi</p>")
        #expect(ArtifactHTML.sandboxed("Plain text") == meta + "Plain text")
        #expect(ArtifactHTML.sandboxed("") == meta)
        // An unfinished comment or doctype ends the prelude where it starts.
        #expect(ArtifactHTML.sandboxed("<!-- open <p>") == meta + "<!-- open <p>")
        #expect(ArtifactHTML.sandboxed("  <!doctype html") == "  " + meta + "<!doctype html")
    }

    /// What WebKit decides for a load under the rule list: the rules apply in order, a
    /// matching block blocks and a later matching `ignore-previous-rules` lifts it.
    /// `url-filter` is a regular expression matched without regard to case.
    static func blocked(_ url: String, _ type: String) throws -> Bool {
        let data = Data(ArtifactRules.json.utf8)
        let rules = try #require(try JSONSerialization.jsonObject(with: data) as? [[String: Any]])
        var blocked = false
        for rule in rules {
            let trigger = try #require(rule["trigger"] as? [String: Any])
            let action = try #require(rule["action"] as? [String: Any])
            let filter = try #require(trigger["url-filter"] as? String)
            let pattern = try NSRegularExpression(pattern: filter, options: .caseInsensitive)
            let range = NSRange(url.startIndex..., in: url)
            guard pattern.firstMatch(in: url, range: range) != nil else { continue }
            if let types = trigger["resource-type"] as? [String], !types.contains(type) {
                continue
            }
            blocked = try #require(action["type"] as? String) == "block"
        }
        return blocked
    }

    @Test func theRuleListLetsInOnlyTheListedHostsOverHTTPS() throws {
        let allowed: [(String, String)] = [
            ("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js", "script"),
            ("https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js", "script"),
            ("https://unpkg.com/react@18.3.1/umd/react.production.min.js", "script"),
            ("https://cdn.tailwindcss.com/3.4.3", "script"),
            ("https://code.jquery.com/jquery-3.7.1.min.js", "script"),
            ("https://fonts.googleapis.com/css2?family=Inter&display=swap", "style-sheet"),
            ("https://fonts.gstatic.com/s/inter/v13/a.woff2", "font"),
            ("HTTPS://CDNJS.CLOUDFLARE.COM/x.js", "script"),
        ]
        for (url, type) in allowed {
            #expect(try !Self.blocked(url, type), "\(url) as \(type)")
        }
        let refused: [(String, String)] = [
            // Look-alike hosts, other schemes and a listed host only in the path or query.
            ("https://cdnjs.cloudflare.com.evil.com/x.js", "script"),
            ("https://cdnjsxcloudflare.com/x.js", "script"),
            ("https://evil-cdnjs.cloudflare.com/x.js", "script"),
            ("http://cdnjs.cloudflare.com/x.js", "script"),
            ("https://unpkg.com.evil.com/react.js", "script"),
            ("https://unpkg.com@evil.com/react.js", "script"),
            ("https://unpkg.company.com/react.js", "script"),
            ("https://evil.com/?u=https://unpkg.com/react.js", "script"),
            ("https://evil.com/https://code.jquery.com/x.js", "script"),
            ("wss://code.jquery.com/x", "websocket"),
            // jsDelivr outside npm, such as straight from GitHub.
            ("https://cdn.jsdelivr.net/gh/evil/repo/x.js", "script"),
            ("https://cdn.jsdelivr.net/npmx/x.js", "script"),
            // A listed host for anything but its own kind of load.
            ("https://cdnjs.cloudflare.com/x.css", "style-sheet"),
            ("https://cdnjs.cloudflare.com/x.png", "image"),
            ("https://cdnjs.cloudflare.com/data.json", "fetch"),
            ("https://cdnjs.cloudflare.com/page.html", "document"),
            ("https://fonts.googleapis.com/x.js", "script"),
            ("https://fonts.gstatic.com/x.js", "script"),
            ("https://fonts.gstatic.com.evil.com/a.woff2", "font"),
            ("https://evil.com/a.woff2", "font"),
            ("https://example.com/", "document"),
            ("https://example.com/x.js", "script"),
        ]
        for (url, type) in refused {
            #expect(try Self.blocked(url, type), "\(url) as \(type)")
        }
    }

    @Test func theRuleListAnchorsEveryHostAndHasItsOwnName() throws {
        let data = Data(ArtifactRules.json.utf8)
        let rules = try #require(try JSONSerialization.jsonObject(with: data) as? [[String: Any]])
        let filters = rules.compactMap {
            ($0["trigger"] as? [String: Any])?["url-filter"] as? String
        }
        #expect(filters.first == ".*")
        #expect(filters.count == rules.count)
        for filter in filters.dropFirst() {
            #expect(filter.hasPrefix(#"^https://"#) && filter.hasSuffix("/"), "\(filter)")
        }
        // Every script host in the page's policy has its rule.
        let hosts = ArtifactHTML.policy.split(separator: ";").first { $0.contains("script-src") }!
            .split(separator: " ").filter { $0.hasPrefix("https://") }
        #expect(hosts.count == 5)
        for host in hosts {
            let url = host.hasSuffix("/") ? "\(host)x.js" : "\(host)/x.js"
            #expect(try !Self.blocked(url, "script"), "\(host)")
        }
        // A list compiled under the B79 name is cached by WebKit; this one needs its own.
        #expect(ArtifactRules.identifier != "nest-artifact-block-everything")
        #expect(!ArtifactRules.identifier.isEmpty)
    }

    @Test func aTitleBecomesAFileName() {
        #expect(
            ArtifactFile.name(title: "Options compared", kind: .markdown) == "Options compared.md")
        #expect(ArtifactFile.name(title: "A/B: tests?  <v2>", kind: .html) == "A B tests v2.html")
        #expect(ArtifactFile.name(title: "..hidden. ", kind: .markdown) == "hidden.md")
        #expect(ArtifactFile.name(title: "\n\t", kind: .unknown) == "Artifact.txt")
        let long = String(repeating: "x", count: 300)
        #expect(ArtifactFile.name(title: long, kind: .html).count == 125)
        #expect(
            [ArtifactKind.slides, .document, .design, .designSystem].map {
                ArtifactFile.name(title: "Plan", kind: $0)
            } == ["Plan.md", "Plan.md", "Plan.json", "Plan.json"])
        #expect(ArtifactFile.pdfName(title: "Q3: review") == "Q3 review.pdf")
        #expect(ArtifactFile.pdfName(title: "") == "Artifact.pdf")
    }

    @Test func onlySlidesAndDocumentsExportAPDF() throws {
        let slides = try #require(ArtifactPrint.layout(.slides))
        // The template's 1280 by 720 stage, at 72 points per 96 CSS pixels.
        #expect(slides.width == 960)
        #expect(slides.height == 540)
        #expect(slides.landscape)
        #expect(slides.margin == 0)
        let document = try #require(ArtifactPrint.layout(.document))
        #expect(document.width == 595)
        #expect(document.height == 842)
        #expect(!document.landscape)
        #expect(document.margin == 36)
        for kind in [ArtifactKind.markdown, .html, .design, .designSystem, .unknown] {
            #expect(ArtifactPrint.layout(kind) == nil)
        }
    }

    @Test func theViewsWordsReadPlainly() {
        #expect(ArtifactText.origin(Fixture.artifact()) == "Pick a queue")
        #expect(ArtifactText.origin(Fixture.artifact(chatDeleted: true)) == "Deleted chat")
        #expect(ArtifactText.origin(Fixture.artifact(chatTitle: nil)) == "Deleted chat")
        #expect(
            ArtifactText.origin(Fixture.artifact(chatDeleted: true, pixieName: "Reviewer"))
                == "Reviewer")
        let now = Fixture.date("2026-10-17T10:00:00Z")
        #expect(ArtifactText.when(now - 20, now: now) == "now")
        #expect(ArtifactText.when(now - 540, now: now) == "9m ago")
        #expect(ArtifactText.kind(.markdown) == "Markdown")
        #expect(ArtifactText.kind(.html) == "HTML")
        #expect(ArtifactText.kind(.unknown) == "Document")
        #expect(
            [ArtifactKind.slides, .document, .design, .designSystem].map(ArtifactText.kind) == [
                "Slides", "Document", "Design", "Design system",
            ])
        #expect(
            [ArtifactKind.markdown, .html, .slides, .document, .design, .designSystem, .unknown]
                .map(\.symbol) == [
                    "doc.richtext", "chevron.left.forwardslash.chevron.right", "play.rectangle",
                    "doc.text", "rectangle.3.group", "swatchpalette", "doc.richtext",
                ])
        #expect(ArtifactText.version(2, of: 3) == "Version 2 of 3")
        let artifact = Fixture.artifact(kind: "document")
        #expect(
            ArtifactText.line(artifact, author: .agent, saved: now - 540, now: now)
                == "Document · Pick a queue · saved 9m ago")
        #expect(
            ArtifactText.line(artifact, author: .user, saved: now - 540, now: now)
                == "Document · Pick a queue · Edited by you 9m ago")
        #expect(
            ArtifactText.line(artifact, author: .unknown, saved: now, now: now)
                == "Document · Pick a queue · saved now")
        #expect(ArtifactText.empty(.chat("s1")) == "This chat has saved no artifacts yet.")
        #expect(
            ArtifactText.empty(.project("cv-page"))
                == "No chat in this project has saved an artifact yet.")
        #expect(ArtifactText.empty(.pixie("p1")) == "This pixie has saved no artifacts yet.")
        #expect(ArtifactText.empty(.pixies) == "No pixie has saved an artifact yet.")
        #expect(
            [ArtifactQuery.chat("s1"), .project("r"), .pixie("p"), .pixies].map(\.label) == [
                "This chat", "Whole project", "This pixie", "All pixies",
            ])
        #expect(ArtifactText.deleted == "Deleted")
        #expect([0, -1, 1, 99, 100].map(ArtifactText.badge) == [nil, nil, "1", "99", "99+"])
    }

    @Test func aCardSaysSavedOrItsVersion() {
        func card(_ action: String, _ version: Int) -> ArtifactCard {
            Fixture.decode(
                ArtifactCard.self,
                json:
                    #"{"artifact_id": "a1", "version": \#(version), "title": "T", "kind": "markdown", "action": "\#(action)"}"#
            )
        }
        #expect(ArtifactText.cardState(card("created", 1)) == "Saved")
        #expect(ArtifactText.cardState(card("updated", 3)) == "Version 3")
        #expect(card("edited", 4).action == .edited)
        #expect(ArtifactText.cardState(card("edited", 4)) == "Version 4")
        #expect(card("renamed", 2).action == .unknown)
        #expect(ArtifactText.cardState(card("renamed", 2)) == "Saved")
    }

    @Test func queriesMatchTheirArtifacts() {
        let chat = Fixture.artifact()
        let pixie = Fixture.artifact(repo: "pixie:p1", session: "pc", pixie: "p1")
        #expect(ArtifactQuery.chat("s1").matches(chat))
        #expect(!ArtifactQuery.chat("s2").matches(chat))
        #expect(ArtifactQuery.project("cv-page").matches(chat))
        #expect(!ArtifactQuery.project("cv-page").matches(pixie))
        #expect(ArtifactQuery.pixie("p1").matches(pixie))
        #expect(!ArtifactQuery.pixie("p1").matches(chat))
        #expect(ArtifactQuery.pixies.matches(pixie))
        #expect(!ArtifactQuery.pixies.matches(chat))
    }

    @Test func theSwitchOffersEachTabsViews() {
        #expect(ProjectView.choices(pixies: false) == [.workspace, .board, .artifacts])
        #expect(ProjectView.choices(pixies: true) == [.workspace, .artifacts])
        #expect(ProjectView.allTitles == ["Workspace", "Board", "Artifacts"])
    }

    // MARK: Store

    @Test func listsLoadByTheirFiltersNewestFirst() async throws {
        let store = store(
            [
                Fixture.artifact(id: "a2"), Fixture.artifact(id: "a1", session: "s2"),
                Fixture.artifact(id: "p", repo: "pixie:p1", session: "pc", pixie: "p1"),
            ], unseen: 3)
        #expect(store.list(.chat("s1")) == nil)
        try await store.load(.chat("s1"))
        try await store.load(.project("cv-page"))
        try await store.load(.pixie("p1"))
        try await store.load(.pixies)
        try await store.loadUnseen()
        #expect(
            api.calls == [
                "artifacts session=s1", "artifacts repo=cv-page", "artifacts pixie=p1",
                "artifacts", "unseenArtifacts",
            ])
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a2"])
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a2", "a1"])
        #expect(store.list(.pixie("p1"))?.map(\.id) == ["p"])
        // The daemon lists every artifact without a filter; only pixies' are kept.
        #expect(store.list(.pixies)?.map(\.id) == ["p"])
        #expect(store.unseen == 3)
        #expect(store.artifact("a1")?.sessionID == "s2")
        #expect(store.availability(of: "a1") == .available)
        #expect(store.availability(of: "zz") == .unknown)
    }

    @Test func theViewStartsNarrowAndSwitchesWide() async throws {
        let store = store([
            Fixture.artifact(id: "a2", session: "s2"), Fixture.artifact(id: "a1"),
        ])
        api.set {
            $0.artifactContents = [
                "a1/3": Fixture.content("a1", 3), "a2/3": Fixture.content("a2", 3),
            ]
        }
        #expect(store.query == nil)
        try await store.open()
        try await store.setWide(true)
        #expect(store.selection == nil)
        #expect(api.calls.isEmpty)

        store.show(ArtifactScope(narrow: .chat("s1"), wide: .project("cv-page")))
        #expect(store.query == .chat("s1"))
        try await store.open()
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a1"])
        // The newest opens in the reader, at its latest version, which marks it seen.
        #expect(store.selection == ArtifactSelection(id: "a1", version: 3))
        #expect(store.selected?.seen == true)
        #expect(store.selectedContent?.artifactID == "a1")

        try await store.setWide(true)
        #expect(store.query == .project("cv-page"))
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a2", "a1"])
        #expect(store.selection?.id == "a1")
        try await store.setWide(false)
        #expect(store.query == .chat("s1"))
        #expect(api.calls.filter { $0.hasPrefix("artifacts") }.count == 2)

        // The same scope again keeps the switch; another scope starts narrow.
        try await store.setWide(true)
        store.show(ArtifactScope(narrow: .chat("s1"), wide: .project("cv-page")))
        #expect(store.showsWide)
        store.show(ArtifactScope(narrow: .chat("s2"), wide: .project("cv-page")))
        #expect(!store.showsWide)
        #expect(store.query == .chat("s2"))
        // A narrow list without the selection moves it to its newest.
        try await store.setWide(false)
        #expect(store.selection?.id == "a2")

        store.show(ArtifactScope(narrow: nil, wide: .pixies))
        #expect(store.query == .pixies)
        try await store.open()
        #expect(store.list(.pixies)?.isEmpty == true)
        #expect(store.selection == nil)
    }

    @Test func stepsThroughVersionsAndMarksOnlyTheLatestSeen() async throws {
        let store = store([Fixture.artifact(latest: 3)], unseen: 2)
        try await store.loadUnseen()
        api.set {
            $0.artifactContents = [
                "a1/1": Fixture.content("a1", 1, "one"), "a1/2": Fixture.content("a1", 2, "two"),
                "a1/3": Fixture.content("a1", 3, "three"),
            ]
        }
        #expect(!store.canStep(by: 1))
        try await store.step(by: 1)
        try await store.select("a1", version: 2)
        #expect(store.selectedContent?.content == "two")
        #expect(store.selected?.seen == false)
        #expect(store.canStep(by: -1))
        #expect(store.canStep(by: 1))
        #expect(!store.canStep(by: 2))
        try await store.step(by: -1)
        #expect(store.selection?.version == 1)
        try await store.step(by: -1)
        #expect(store.selection?.version == 1)
        try await store.step(by: 2)
        #expect(store.selectedContent?.content == "three")
        #expect(store.selected?.seen == true)
        #expect(store.unseen == 1)
        #expect(api.calls.filter { $0.hasPrefix("markArtifactSeen") } == ["markArtifactSeen a1"])
        // Read versions are kept; out of range versions show the nearest. The latest is
        // shown already; moving back to version 1 reads its page again (B88).
        try await store.select("a1", version: 9)
        try await store.select("a1", version: 0)
        #expect(store.selection?.version == 1)
        #expect(api.calls.filter { $0.hasPrefix("artifactContent") }.count == 4)
        #expect(store.content(ArtifactSelection(id: "a1", version: 2))?.content == "two")
    }

    // MARK: Saving a document (B88)

    func documentStore(latest: Int = 2) async throws -> ArtifactsStore {
        let store = store([Fixture.artifact(kind: "document", latest: latest, seen: true)])
        api.set {
            $0.artifactContents = [
                "a1/1": Fixture.content("a1", 1, "one"), "a1/2": Fixture.content("a1", 2, "two"),
                "a1/3": Fixture.content("a1", 3, "three"),
            ]
        }
        try await store.select("a1")
        return store
    }

    @Test func savingTheLatestDocumentMovesTheReaderToTheNewVersion() async throws {
        let store = try await documentStore()
        let page = ArtifactSelection(id: "a1", version: 2)
        let version = try await store.saveDocument(page, content: "# New", baseVersion: 2)
        #expect(version == 3)
        #expect(api.calls.contains("saveArtifactVersion a1 base=2 # New"))
        #expect(store.selection == ArtifactSelection(id: "a1", version: 3))
        #expect(store.selectedContent?.content == "three")
        #expect(store.selected?.latestVersion == 3)
        #expect(store.selected?.versionCount == 3)
        #expect(store.selected?.title == "Edited")
        #expect(store.selected?.updatedAt == Fixture.date("2026-10-17T10:00:00Z"))
        #expect(store.canStep(by: -1))
    }

    @Test func aSaveWhileTheReaderMovedOnLeavesItThere() async throws {
        let store = try await documentStore()
        try await store.select("a1", version: 1)
        let version = try await store.saveDocument(
            ArtifactSelection(id: "a1", version: 2), content: "x", baseVersion: 2)
        #expect(version == 3)
        #expect(store.selection == ArtifactSelection(id: "a1", version: 1))
        #expect(store.artifact("a1")?.latestVersion == 3)
    }

    @Test func onlyTheLatestVersionOfADocumentSaves() async throws {
        let store = try await documentStore()
        await #expect(throws: ArtifactsStore.SaveRefused.self) {
            try await store.saveDocument(
                ArtifactSelection(id: "a1", version: 1), content: "x", baseVersion: 1)
        }
        await #expect(throws: ArtifactsStore.SaveRefused.self) {
            try await store.saveDocument(
                ArtifactSelection(id: "zz", version: 1), content: "x", baseVersion: 1)
        }
        let markdown = self.store([Fixture.artifact(latest: 1)])
        try? await markdown.select("a1")
        await #expect(throws: ArtifactsStore.SaveRefused.self) {
            try await markdown.saveDocument(
                ArtifactSelection(id: "a1", version: 1), content: "x", baseVersion: 1)
        }
        #expect(!api.calls.contains { $0.hasPrefix("saveArtifactVersion") })
    }

    @Test func aRefusedSaveKeepsTheReaderWhereItIs() async throws {
        let store = try await documentStore()
        api.fail("saveArtifactVersion", with: APIError.conflict("The document changed."))
        await #expect(throws: APIError.conflict("The document changed.")) {
            try await store.saveDocument(
                ArtifactSelection(id: "a1", version: 2), content: "x", baseVersion: 2)
        }
        #expect(store.selection == ArtifactSelection(id: "a1", version: 2))
        #expect(store.selected?.latestVersion == 2)
    }

    @Test func anArtifactOpenedFromACardIsReadFirst() async throws {
        let store = store([Fixture.artifact(id: "a9", latest: 2, seen: true)])
        api.set { $0.artifactContents = ["a9/1": Fixture.content("a9", 1)] }
        try await store.select("a9", version: 1)
        #expect(api.calls == ["artifact a9", "artifactContent a9/1"])
        #expect(store.selected?.id == "a9")

        await #expect(throws: APIError.notFound("artifact not found")) {
            try await store.select("gone")
        }
        #expect(store.availability(of: "gone") == .deleted)
        #expect(store.selection?.id == "a9")
    }

    @Test func aFailedSeenMarkLeavesItUnseen() async throws {
        let store = store([Fixture.artifact(latest: 1)], unseen: 1)
        try await store.loadUnseen()
        api.set { $0.artifactContents = ["a1/1": Fixture.content("a1", 1)] }
        api.fail("markArtifactSeen")
        try await store.select("a1")
        #expect(store.selected?.seen == false)
        #expect(store.unseen == 1)
    }

    @Test func aSeenEventFirstIsNotCountedTwice() async throws {
        let store = store([Fixture.artifact(latest: 1)], unseen: 2)
        try await store.loadUnseen()
        try await store.load(.project("cv-page"))
        store.apply(
            Fixture.event(
                EventType.artifactSeen, #"{"artifact_id": "a1", "unseen": 1}"#, session: nil))
        api.set { $0.artifactContents = ["a1/1": Fixture.content("a1", 1)] }
        try await store.select("a1")
        #expect(store.unseen == 1)
        #expect(api.calls.contains("markArtifactSeen a1") == false)
    }

    @Test func cardsLearnOnceWhetherTheirArtifactIsThere() async throws {
        let store = store([Fixture.artifact(id: "a1")])
        let gate = AsyncStream<Void>.makeStream()
        api.set { $0.gates["artifact"] = gate.stream }
        let first = Task { await store.check("a1") }
        let second = Task { await store.check("a1") }
        try await waitFor { api.calls.count == 1 }
        gate.continuation.finish()
        await first.value
        await second.value
        #expect(api.calls == ["artifact a1"])
        #expect(store.availability(of: "a1") == .available)
        await store.check("a1")
        #expect(api.calls.count == 1)

        api.set { $0.gates = [:] }
        await store.check("gone")
        #expect(store.availability(of: "gone") == .deleted)
        api.fail("artifact")
        await store.check("other")
        #expect(store.availability(of: "other") == .unknown)
    }

    @Test func deletingRemovesItEverywhere() async throws {
        let store = store([Fixture.artifact(id: "a2"), Fixture.artifact(id: "a1", seen: true)])
        api.set { $0.artifactContents = ["a2/3": Fixture.content("a2", 3)] }
        store.show(ArtifactScope(narrow: nil, wide: .project("cv-page")))
        try await store.open()
        try await store.load(.chat("s1"))
        #expect(store.selection?.id == "a2")
        api.set { $0.unseenArtifacts = 4 }
        try await store.loadUnseen()

        api.set { $0.artifactContents["a1/3"] = Fixture.content("a1", 3) }
        try await store.delete("a2")
        #expect(api.calls.contains("deleteArtifact a2"))
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a1"])
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a1"])
        #expect(store.availability(of: "a2") == .deleted)
        #expect(store.content(ArtifactSelection(id: "a2", version: 3)) == nil)
        // The next one opens; it was seen, so the count only lost the deleted one.
        #expect(store.selection?.id == "a1")
        #expect(store.unseen == 4)

        api.fail("deleteArtifact")
        await #expect(throws: APIError.self) { try await store.delete("a1") }
        #expect(store.artifact("a1") != nil)
    }

    @Test func deletingAnUnseenOneLowersTheCount() async throws {
        let store = store([Fixture.artifact(id: "a1")], unseen: 1)
        try await store.loadUnseen()
        try await store.load(.chat("s1"))
        try await store.delete("a1")
        #expect(store.unseen == 0)
        #expect(store.selection == nil)
    }

    @Test func savedEventsMoveItToTheTopOfTheListsItMatches() async throws {
        let store = store([Fixture.artifact(id: "a2"), Fixture.artifact(id: "a1", session: "s2")])
        try await store.load(.project("cv-page"))
        try await store.load(.chat("s2"))
        try await store.load(.pixie("p1"))
        store.apply(
            Self.savedEvent(
                Fixture.artifactJSON(id: "a1", title: "New title", session: "s2", latest: 4),
                version: 4, unseen: 5))
        #expect(store.unseen == 5)
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a1", "a2"])
        #expect(store.list(.chat("s2"))?.map(\.id) == ["a1"])
        #expect(store.list(.pixie("p1"))?.isEmpty == true)
        #expect(store.artifact("a1")?.title == "New title")
        #expect(store.artifact("a1")?.latestVersion == 4)

        store.apply(Self.savedEvent(Fixture.artifactJSON(id: "a3"), unseen: 6))
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a3", "a1", "a2"])
        #expect(store.list(.chat("s2"))?.map(\.id) == ["a1"])
    }

    @Test func seenDeletedAndGoneChatEventsPatchTheStore() async throws {
        let store = store([
            Fixture.artifact(id: "a1"), Fixture.artifact(id: "a2", session: "s2"),
            Fixture.artifact(id: "p", repo: "pixie:p1", session: "pc", pixie: "p1"),
        ])
        api.set { $0.artifactContents = ["a1/3": Fixture.content("a1", 3)] }
        try await store.load(.project("cv-page"))
        try await store.load(.pixies)
        store.apply(
            Fixture.event(
                EventType.artifactSeen, #"{"artifact_id": "a2", "unseen": 7}"#, session: nil))
        #expect(store.artifact("a2")?.seen == true)
        #expect(store.unseen == 7)

        store.apply(Fixture.event(EventType.sessionDeleted, #"{"session_id": "s1"}"#))
        #expect(store.artifact("a1")?.chatDeleted == true)
        #expect(store.artifact("a2")?.chatDeleted == false)
        store.apply(Fixture.event(EventType.pixieDeleted, #"{"pixie_id": "p1"}"#))
        #expect(store.artifact("p")?.chatDeleted == true)

        try await store.select("a1")
        store.apply(
            Fixture.event(
                EventType.artifactDeleted, #"{"artifact_id": "a1", "unseen": 2}"#, session: nil))
        #expect(store.unseen == 2)
        #expect(store.selection == nil)
        #expect(store.artifact("a1") == nil)
        #expect(store.list(.project("cv-page"))?.map(\.id) == ["a2"])
        #expect(store.list(.pixies)?.map(\.id) == ["p"])

        store.apply(Fixture.event(EventType.notify, "{}"))
        #expect(store.unseen == 2)
    }

    @Test func aReloadReadsTheCountTheListsAndTheOpenOne() async throws {
        let store = store([Fixture.artifact(id: "a1"), Fixture.artifact(id: "a2")])
        api.set { $0.artifactContents = ["a1/3": Fixture.content("a1", 3)] }
        try await store.load(.chat("s1"))
        try await store.select("a1")
        api.set {
            $0.artifacts = [Fixture.artifact(id: "a3"), Fixture.artifact(id: "a1")]
            $0.unseenArtifacts = 9
        }
        try await store.reload()
        #expect(store.unseen == 9)
        #expect(store.list(.chat("s1"))?.map(\.id) == ["a3", "a1"])
        #expect(api.calls.suffix(3) == ["unseenArtifacts", "artifacts session=s1", "artifact a1"])

        // The open one was deleted while away: the reader leaves it.
        api.set { $0.artifacts = [] }
        try await store.reload()
        #expect(store.selection == nil)
        #expect(store.availability(of: "a1") == .deleted)
    }

    @Test func liveSyncLoadsAndRoutesArtifacts() async throws {
        let model = AppModel(api: api, events: ManualEventSource(), preferences: MemoryStore())
        api.set { $0.unseenArtifacts = 4 }
        await model.live.refresh()
        #expect(model.artifacts.unseen == 4)
        model.live.route(
            Fixture.event(
                EventType.artifactSeen, #"{"artifact_id": "a1", "unseen": 3}"#, session: nil))
        #expect(model.artifacts.unseen == 3)
    }

    // MARK: Transcript

    @Test func aSavedArtifactIsACardAndItsCallHides() async throws {
        let transcript = TranscriptStore(sessionID: "s1", api: api)
        try await transcript.load()
        let input = ##"{"title": "Plan", "kind": "markdown", "content": "# A long document"}"##
        let events = [
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_use", "id": "t1", "name": "mcp__nest__create_artifact", "input": \#(input)}]}"#,
                id: 1),
            Fixture.event(
                EventType.sessionArtifact,
                #"{"artifact_id": "a1", "version": 1, "title": "Plan", "kind": "markdown", "action": "created"}"#,
                id: 2),
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_use", "id": "t2", "name": "mcp__nest__update_artifact", "input": {"artifact_id": "x", "content": "y"}}]}"#,
                id: 3),
        ]
        for event in events {
            transcript.receive(event)
        }
        // While it runs, the call shows, by its title and never its content.
        #expect(transcript.visibleItems.map(\.id) == ["t1", "e2", "t2"])
        guard case .tool(let call) = transcript.visibleItems[0].content,
            case .artifact(let card) = transcript.visibleItems[1].content
        else {
            Issue.record("not a call and a card")
            return
        }
        #expect(card.artifactID == "a1")
        #expect(ToolSummary.kind(of: call.name) == .artifact)
        #expect(ToolSummary.name(of: call.name) == "Save artifact")
        #expect(ToolSummary.name(of: ArtifactTools.update) == "Update artifact")
        #expect(ToolSummary.name(of: "Read") == "Read")
        #expect(ToolSummary.argument(of: call) == "Plan")
        #expect(ToolSummary.argument(tool: ArtifactTools.update, input: .object([:])) == "")
        #expect(ArtifactTools.contains(ArtifactTools.create))
        #expect(!ArtifactTools.contains("Write"))

        transcript.receive(
            Fixture.event(
                EventType.sessionMessage,
                #"{"blocks": [{"type": "tool_result", "tool_use_id": "t1", "content": "Saved artifact a1 (version 1): Plan."}, {"type": "tool_result", "tool_use_id": "t2", "content": "unknown artifact 'x'", "is_error": true}]}"#,
                id: 4))
        // Saved: the card says it. Refused: the call stays to read why.
        #expect(transcript.visibleItems.map(\.id) == ["e2", "t2"])
    }

    @Test func artifactCallsReadAsSavesInSummaries() {
        let input = JSONValue.object(["title": .string("Plan")])
        let calls = [
            ToolCall(
                id: "1", name: ArtifactTools.create, input: input, result: nil, isError: false),
            ToolCall(
                id: "2", name: ArtifactTools.update, input: input, result: "ok", isError: false),
        ]
        #expect(ToolActivity.summary(calls, running: true) == "Saving 2 artifacts")
        #expect(ToolActivity.summary(Array(calls.prefix(1)), running: false) == "Saved 1 artifact")
        let step = CallStep(id: "s", kind: .tool(name: ArtifactTools.create, input: input))
        #expect(step.line == "Save artifact Plan")
    }

    @Test func thePaletteOffersTheArtifactsView() {
        let app = AppStore(api: api, store: MemoryStore())
        let sessions = SessionsStore(api: api, approvals: ApprovalsStore(api: api))
        app.openProject("cv-page")
        func titles() -> [String] {
            CommandPalette.catalog(app: app, sessions: sessions).items.map(\.title)
        }
        #expect(titles().contains("Show the Artifacts view"))
        let item = CommandPalette.catalog(app: app, sessions: sessions).items.first {
            $0.title == "Show the Artifacts view"
        }
        #expect(item?.action == .showView(.artifacts))
        #expect(item?.glyph == .artifacts)
        app.update { $0.view = .artifacts }
        #expect(!titles().contains("Show the Artifacts view"))
        #expect(titles().contains("Show the Workspace view"))
    }
}

extension ProjectView {
    fileprivate static var allTitles: [String] {
        choices(pixies: false).map(\.title)
    }
}
