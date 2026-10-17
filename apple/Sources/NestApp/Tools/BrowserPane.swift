import AppKit
import NestKit
import Observation
import SwiftUI
import WebKit

/// One browser pane's web view and what its toolbar shows.
@MainActor @Observable
final class BrowserSession: NSObject, WKNavigationDelegate {
    /// Finds the local servers; snapshots answer with sample servers.
    static var scan: @MainActor () async -> [LocalServer] = {
        await LocalServers.scan(runner: ProcessRunner())
    }
    /// Snapshots show this page in place of loading the address.
    static var sampleHTML: String?

    @ObservationIgnored let view = NestWebView()
    /// The page's address, nil before the first page.
    private(set) var url: URL?
    private(set) var title = ""
    private(set) var canGoBack = false
    private(set) var canGoForward = false
    private(set) var isLoading = false
    /// Why the last page did not load.
    private(set) var failure: String?
    @ObservationIgnored private let navigated: (String) -> Void
    @ObservationIgnored private var observations: [NSKeyValueObservation] = []

    init(url: String?, navigated: @escaping (String) -> Void) {
        self.navigated = navigated
        super.init()
        view.navigationDelegate = self
        observations = [
            view.observe(\.url) { [weak self] web, _ in
                MainActor.assumeIsolated { self?.urlChanged(web.url) }
            },
            view.observe(\.title) { [weak self] web, _ in
                MainActor.assumeIsolated { self?.title = web.title ?? "" }
            },
            view.observe(\.canGoBack) { [weak self] web, _ in
                MainActor.assumeIsolated { self?.canGoBack = web.canGoBack }
            },
            view.observe(\.canGoForward) { [weak self] web, _ in
                MainActor.assumeIsolated { self?.canGoForward = web.canGoForward }
            },
            view.observe(\.isLoading) { [weak self] web, _ in
                MainActor.assumeIsolated { self?.isLoading = web.isLoading }
            },
        ]
        if let address = url.flatMap(URL.init(string:)) {
            load(address)
        }
    }

    /// Opens what was typed in the address field.
    func go(_ input: String) {
        if let address = BrowserAddress.url(from: input) {
            load(address)
        }
    }

    func load(_ address: URL) {
        failure = nil
        if let html = Self.sampleHTML {
            view.loadHTMLString(html, baseURL: address)
        } else {
            view.load(URLRequest(url: address))
        }
    }

    func reload() {
        failure = nil
        if view.url == nil, let url {
            load(url)
        } else {
            view.reload()
        }
    }

    func end() {
        view.stopLoading()
        observations = []
        view.navigationDelegate = nil
    }

    private func urlChanged(_ newURL: URL?) {
        guard let newURL, newURL != url else { return }
        url = newURL
        navigated(newURL.absoluteString)
    }

    func webView(
        _ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: any Error
    ) {
        fail(error)
    }

    func webView(
        _ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error
    ) {
        fail(error)
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        failure = nil
    }

    /// A cancelled load (a new address typed meanwhile) is not a failure.
    private func fail(_ error: any Error) {
        let error = error as NSError
        guard !(error.domain == NSURLErrorDomain && error.code == NSURLErrorCancelled) else {
            return
        }
        failure = error.localizedDescription
    }
}

/// The web view; dropping a dragged chat on it goes to the workspace, not the page.
final class NestWebView: WKWebView {
    override func registerForDraggedTypes(_ newTypes: [NSPasteboard.PasteboardType]) {}
}

private struct WebHost: NSViewRepresentable {
    let session: BrowserSession
    let focus: () -> Void

    func makeNSView(context: Context) -> PaneContentView {
        let container = PaneContentView()
        container.onClick = focus
        container.show(session.view)
        return container
    }

    func updateNSView(_ container: PaneContentView, context: Context) {
        container.onClick = focus
        container.show(session.view)
        container.isHidden = context.environment.paneHidden
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView: PaneContentView, context: Context
    ) -> CGSize? {
        PaneContentView.fill(proposal)
    }
}

/// A browser pane: back, forward, reload, the address field and local servers in the
/// header, then the page.
struct BrowserPaneView: View {
    let pane: ToolPane
    @Environment(Shell.self) private var shell

    var body: some View {
        let id = pane.id
        let session = shell.tools.browser(for: pane) { [shell] url in
            shell.browserNavigated(id, to: url)
        }
        VStack(spacing: 0) {
            ToolPaneHeader(pane: pane.id, title: session.title.isEmpty ? pane.title : session.title)
            {
                BrowserToolbar(session: session)
            }
            Rectangle().fill(Palette.divider).frame(height: 1)
            ZStack {
                if session.url == nil {
                    StartPage(session: session)
                } else {
                    // Inside the panel's 1 point ring.
                    WebHost(session: session) { shell.focusPane(id) }
                        .padding([.horizontal, .bottom], 1)
                    if let failure = session.failure {
                        LoadFailure(text: failure) { session.reload() }
                    }
                }
            }
        }
        .modifier(PaneChrome(pane: pane.id))
    }
}

private struct BrowserToolbar: View {
    let session: BrowserSession
    @State private var text = ""
    @State private var showsServers = false
    @FocusState private var editing: Bool
    @Environment(\.accentColors) private var accent

    var body: some View {
        HStack(spacing: 2) {
            navButton(Icon.chevronLeft, "Back", enabled: session.canGoBack) {
                session.view.goBack()
            }
            navButton(Icon.chevronRight, "Forward", enabled: session.canGoForward) {
                session.view.goForward()
            }
            navButton(session.isLoading ? Icon.close : Icon.refresh, "Reload", enabled: true) {
                if session.isLoading {
                    session.view.stopLoading()
                } else {
                    session.reload()
                }
            }
            TextField("", text: $text)
                .accessibilityLabel("Address")
                .overlay(alignment: .leading) {
                    Placeholder(text: "Address, localhost port or search", shown: text.isEmpty)
                }
                .textFieldStyle(.plain)
                .font(.ui(TypeSize.ui))
                .focused($editing)
                .onSubmit {
                    session.go(text)
                    editing = false
                }
                .padding(.horizontal, 9)
                .frame(height: 24)
                .background(Palette.soft, in: .rounded(Radius.row))
                .overlay(
                    RoundedRectangle.rounded(Radius.row)
                        .strokeBorder(editing ? accent.focus : .clear, lineWidth: 1)
                )
                .padding(.leading, 4)
                .frame(minWidth: 60)
            Button {
                showsServers.toggle()
            } label: {
                Image(systemName: Icon.server)
                    .font(.system(size: 10.5))
                    .foregroundStyle(Palette.t3)
            }
            .buttonStyle(.nest(.plain, iconOnly: true))
            .help("Local servers")
            .accessibilityLabel("Local servers")
            .popover(isPresented: $showsServers, arrowEdge: .bottom) {
                LocalServerList(session: session) { showsServers = false }
                    .frame(width: 260)
                    .padding(8)
            }
        }
        .onAppear { text = session.url?.absoluteString ?? "" }
        .onChange(of: session.url) { _, url in
            if !editing {
                text = url?.absoluteString ?? ""
            }
        }
    }

    private func navButton(
        _ icon: String, _ label: String, enabled: Bool, action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(Palette.t3)
        }
        .buttonStyle(.nest(.plain, iconOnly: true))
        .disabled(!enabled)
        .help(label)
        .accessibilityLabel(label)
    }
}

/// The listening localhost ports, looked up each time the list shows.
struct LocalServerList: View {
    let session: BrowserSession
    let picked: () -> Void
    @State private var servers: [LocalServer]?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            SectionLabel(text: "Local servers")
                .padding(.horizontal, 8)
                .padding(.bottom, 4)
            if let servers {
                if servers.isEmpty {
                    Text("Nothing is listening on localhost")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                        .padding(8)
                }
                ForEach(servers) { server in
                    Button {
                        session.load(server.url)
                        picked()
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: Icon.globe)
                                .font(.system(size: 10))
                                .foregroundStyle(Palette.t3)
                            Text("localhost:\(String(server.port))")
                                .font(.mono(TypeSize.meta))
                                .foregroundStyle(Palette.link)
                            Spacer(minLength: 8)
                            Text(server.process)
                                .font(.ui(TypeSize.ui))
                                .foregroundStyle(Palette.t3)
                                .lineLimit(1)
                        }
                        .padding(.horizontal, 8)
                        .frame(height: Metrics.rowHeight)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(RowHoverStyle())
                }
            } else {
                HStack(spacing: 8) {
                    Fireflies()
                    Text("Looking for servers")
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .padding(8)
            }
        }
        .task { servers = await BrowserSession.scan() }
    }
}

/// An empty browser: what to type, and the local servers to open.
private struct StartPage: View {
    let session: BrowserSession

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: Icon.globe)
                .font(.system(size: 18, weight: .light))
                .foregroundStyle(Palette.t3)
            Text("Type an address, a localhost port such as 3000, or pick a local server")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .multilineTextAlignment(.center)
            LocalServerList(session: session) {}
                .frame(maxWidth: 300)
                .padding(8)
                .softFill()
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct LoadFailure: View {
    let text: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: Icon.warning)
                .font(.system(size: 18))
                .foregroundStyle(StatusTone.failed.color)
            Text(text)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .multilineTextAlignment(.center)
            Button("Try again", action: retry)
                .buttonStyle(.nest(.soft))
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.windowOpaque)
    }
}
