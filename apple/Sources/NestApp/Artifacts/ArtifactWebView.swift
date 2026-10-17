import AppKit
import NestKit
import SwiftUI
import WebKit

/// An artifact's page, which is untrusted agent output, in a web view that can go nowhere
/// (B79) and load only pinned libraries and fonts (B82): no stored data, a rule list that
/// blocks every other load, the content security policy in the page, only the first
/// navigation (the page itself), no new windows, no script message handlers and no file
/// access. The page is never loaded before the rule list is installed. It takes Nest's
/// light or dark appearance, so `prefers-color-scheme` inside matches the app's theme.
struct ArtifactWebView: NSViewRepresentable {
    let page: String
    /// `ArtifactSandbox.rules()`, read before the view is made.
    let rules: WKContentRuleList

    func makeCoordinator() -> SandboxNavigation {
        SandboxNavigation()
    }

    func makeNSView(context: Context) -> PaneContentView {
        let container = PaneContentView()
        container.layer?.cornerRadius = 0
        let view = NestWebView(frame: .zero, configuration: Self.configuration(rules))
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.appearance = Self.appearance(context.environment.colorScheme)
        container.show(view)
        context.coordinator.webView = view
        view.loadHTMLString(ArtifactHTML.sandboxed(page), baseURL: nil)
        return container
    }

    func updateNSView(_ container: PaneContentView, context: Context) {
        context.coordinator.webView?.appearance = Self.appearance(context.environment.colorScheme)
    }

    /// The scheme SwiftUI resolved from Nest's theme, so the page follows Light, Dark or
    /// Auto as set in Nest and not only the system's.
    private static func appearance(_ scheme: ColorScheme) -> NSAppearance? {
        NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView: PaneContentView, context: Context
    ) -> CGSize? {
        PaneContentView.fill(proposal)
    }

    private static func configuration(_ rules: WKContentRuleList) -> WKWebViewConfiguration {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(rules)
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        return configuration
    }
}

/// Lets the first navigation through, the page's own load, and cancels every later one:
/// link clicks, `location` changes, form posts, frames and refreshes. New windows are
/// never made.
final class SandboxNavigation: NSObject, WKNavigationDelegate, WKUIDelegate {
    private var loaded = false
    weak var webView: WKWebView?

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard !loaded, navigationAction.targetFrame?.isMainFrame == true else {
            decisionHandler(.cancel)
            return
        }
        loaded = true
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        nil
    }
}

/// `ArtifactRules`, compiled once.
@MainActor
enum ArtifactSandbox {
    private static var compiling: Task<WKContentRuleList, any Error>?

    static func rules() async throws -> WKContentRuleList {
        if let compiling {
            return try await compiling.value
        }
        let task = Task { @MainActor in
            guard
                let list = try await WKContentRuleListStore.default().compileContentRuleList(
                    forIdentifier: ArtifactRules.identifier,
                    encodedContentRuleList: ArtifactRules.json)
            else { throw CocoaError(.featureUnsupported) }
            return list
        }
        compiling = task
        do {
            return try await task.value
        } catch {
            compiling = nil
            throw error
        }
    }
}
