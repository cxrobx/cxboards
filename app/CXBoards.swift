// CXBoards.app — a native window around the board server on 127.0.0.1:4870.
//
// The server runs on its own (LaunchAgent com.cx.cxboards.server); this app starts
// it if it isn't up, shows the board, and adds what a browser tab can't:
//   * Finder drops carry real file paths. The page gets the paths (not anonymous
//     File objects), so a dropped bounce is pointed at exactly, never looked up or copied.
//   * alert / confirm / prompt as native sheets (WKWebView shows nothing without them).
//   * Downloads land in ~/Downloads; outside links open in the default browser.
//   * cxboards://b/<board id> opens a board; ⌘N makes a new one.
//
// Build: app/build-app.sh (swiftc, no Xcode project).

import Cocoa
import WebKit

let baseURL = URL(string: "http://127.0.0.1:4870")!
/// `CXBoards --selftest <board id> <file to drop>`: drive the real app against the real server,
/// print what worked as JSON, exit 0 only if everything did. Dialogs answer themselves and
/// nothing opens in other apps while it runs (scripts/selftest-app.sh).
let selfTestArgs: [String]? = {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: "--selftest"), args.count > i + 2 else { return nil }
    return [args[i + 1], args[i + 2]]
}()
let serviceLabel = "com.cx.cxboards.server"
let imageExtensions: Set<String> = ["png", "jpg", "jpeg", "gif", "webp", "svg", "heic"]

@discardableResult
func launchctl(_ arguments: [String]) -> Int32 {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
    process.arguments = arguments
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch { return -1 }
    process.waitUntilExit()
    return process.terminationStatus
}

// MARK: - The web view, with native file drops

final class BoardWebView: WKWebView {
    /// Called with the dropped files and the drop point in page (CSS) coordinates.
    var onFileDrop: (([URL], CGPoint) -> Void)?

    /// Files dragged in from another app (Finder). Drags that start in the page stay the page's.
    private func droppedFiles(_ info: NSDraggingInfo) -> [URL] {
        guard info.draggingSource == nil else { return [] }
        let urls = info.draggingPasteboard.readObjects(
            forClasses: [NSURL.self],
            options: [.urlReadingFileURLsOnly: true]
        ) as? [URL]
        return urls ?? []
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        droppedFiles(sender).isEmpty ? super.draggingEntered(sender) : .copy
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        droppedFiles(sender).isEmpty ? super.draggingUpdated(sender) : .copy
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let files = droppedFiles(sender)
        guard !files.isEmpty, let onFileDrop else { return super.performDragOperation(sender) }
        let local = convert(sender.draggingLocation, from: nil)
        let y = isFlipped ? local.y : bounds.height - local.y
        let zoom = pageZoom > 0 ? pageZoom : 1
        onFileDrop(files, CGPoint(x: local.x / zoom, y: y / zoom))
        return true
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate,
    WKScriptMessageHandler {
    private var window: NSWindow!
    private var webView: BoardWebView!
    private var status: NSTextField!
    private var titleObservation: NSKeyValueObservation?
    private var pendingURL: URL?
    private var ready = false
    private var downloadTargets: [ObjectIdentifier: URL] = [:]
    private var openedOutside: [String] = []
    private var finishedDownloads: [URL] = []
    private var selfTestStarted = false
    private var watching = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        ensureServer { [weak self] ok in
            guard let self else { return }
            if ok {
                self.ready = true
                if let test = selfTestArgs {
                    self.pendingURL = URL(string: "/b/\(test[0])", relativeTo: baseURL)!.absoluteURL
                }
                self.webView.load(URLRequest(url: self.pendingURL ?? baseURL))
                self.pendingURL = nil
            } else {
                self.showServerProblem()
                if selfTestArgs != nil { self.finishSelfTest(["server": false]) } else { self.watchForServer() }
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window.makeKeyAndOrderFront(nil) }
        return true
    }

    /// cxboards://b/<board id> (or cxboards:// for the last board).
    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first, url.scheme == "cxboards" else { return }
        var path = "/"
        if url.host == "b", let id = url.pathComponents.dropFirst().first {
            path = "/b/\(id)"
        }
        let target = URL(string: path, relativeTo: baseURL)!.absoluteURL
        window?.makeKeyAndOrderFront(nil)
        if ready { webView.load(URLRequest(url: target)) } else { pendingURL = target }
    }

    // MARK: Window

    private func buildWindow() {
        let config = WKWebViewConfiguration()
        config.preferences.isElementFullscreenEnabled = true
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        config.mediaTypesRequiringUserActionForPlayback = []
        config.applicationNameForUserAgent = "CXBoards"
        // Borderless, like Onyx: the page knows it's in the app (room for the traffic lights) and
        // hands back mouse-downs on its title band and header, which the window drags by.
        config.userContentController.addUserScript(WKUserScript(
            source: "document.documentElement.classList.add('native')",
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        config.userContentController.add(self, name: "cxDrag")
        // The open board's theme: the page reports it and the window (appearance, background) follows.
        config.userContentController.add(self, name: "cxTheme")

        webView = BoardWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.isInspectable = true
        webView.onFileDrop = { [weak self] files, point in self?.handOver(files, at: point) }

        status = NSTextField(labelWithString: "Starting CXBoards…")
        status.font = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        status.textColor = .secondaryLabelColor
        status.alignment = .center
        status.translatesAutoresizingMaskIntoConstraints = false

        let content = NSView()
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        webView.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(webView)
        content.addSubview(status)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.topAnchor.constraint(equalTo: content.topAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            status.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            status.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            status.widthAnchor.constraint(lessThanOrEqualTo: content.widthAnchor, constant: -80),
        ])

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1440, height: 920),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.title = "CXBoards"  // hidden, but still what the Window menu and Mission Control show
        window.minSize = NSSize(width: 820, height: 520)
        window.contentView = content
        window.tabbingMode = .disallowed
        window.isReleasedWhenClosed = false
        window.center()
        window.setFrameAutosaveName("CXBoardsMain")
        window.collectionBehavior.insert(.fullScreenPrimary)
        // Open in the last board's colours, so there's no flash of the default before the page says.
        let defaults = UserDefaults.standard
        applyTheme(appearance: defaults.string(forKey: "themeAppearance"), ground: defaults.string(forKey: "themeGround"))
        window.makeKeyAndOrderFront(nil)

        // The board's title ("October sessions · CXBoards") becomes the window's.
        titleObservation = webView.observe(\.title, options: [.new]) { [weak self] view, _ in
            guard let title = view.title, !title.isEmpty else { return }
            self?.window.title = title
        }
    }

    // MARK: Server

    /// Health-check the server; if it's down, ask launchd to start it and wait up to 45 s. After a
    /// reboot the LaunchAgent can come up well after the app does (2026-10-05: the server started
    /// 37 s after boot, the old 15 s wait gave up first), and `watchForServer` covers anything later.
    private func ensureServer(_ done: @escaping (Bool) -> Void) {
        checkHealth { [weak self] ok in
            if ok { return done(true) }
            self?.status.stringValue = "Starting the CXBoards server…"
            // Loaded but stopped: kickstart. Not loaded at all (a failed install, a bootout): load it.
            if launchctl(["kickstart", "gui/\(getuid())/\(serviceLabel)"]) != 0 {
                let plist = NSString(string: "~/Library/LaunchAgents/\(serviceLabel).plist").expandingTildeInPath
                _ = launchctl(["bootstrap", "gui/\(getuid())", plist])
            }
            self?.waitForServer(deadline: Date().addingTimeInterval(45), done: done)
        }
    }

    private func waitForServer(deadline: Date, done: @escaping (Bool) -> Void) {
        checkHealth { [weak self] ok in
            if ok { return done(true) }
            if Date() > deadline { return done(false) }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self?.waitForServer(deadline: deadline, done: done) }
        }
    }

    private func checkHealth(_ completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/health"))
        request.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: request) { _, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { completion(ok) }
        }.resume()
    }

    private func showServerProblem() {
        status.stringValue = """
        The CXBoards server isn't answering on 127.0.0.1:4870.

        Install or repair it with:
        ~/Projects/cxboards/scripts/install.sh

        Its log is ~/Library/Logs/cxboards.log · ⌘R tries again
        """
    }

    /// Once the problem page is up, keep checking every 2 s and load the board the moment the
    /// server answers, so the page clears itself instead of waiting for ⌘R.
    private func watchForServer() {
        guard !ready, !watching else { return }
        watching = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self else { return }
            self.watching = false
            guard !self.ready else { return }
            self.checkHealth { ok in
                guard !self.ready else { return }
                if ok {
                    self.ready = true
                    self.webView.load(URLRequest(url: self.pendingURL ?? baseURL))
                    self.pendingURL = nil
                } else {
                    self.watchForServer()
                }
            }
        }
    }

    @objc private func retry() {
        status.stringValue = "Starting CXBoards…"
        ensureServer { [weak self] ok in
            guard let self else { return }
            if ok {
                self.ready = true
                self.webView.load(URLRequest(url: baseURL))
            } else {
                self.showServerProblem()
                self.watchForServer()
            }
        }
    }

    // MARK: Moving the window

    /// The page's title band and header are the title bar now. A web view swallows the mouse, so the
    /// page posts its mouse-down here and the window drags by the event in flight, as Onyx (and Tauri
    /// for cxtasks and cxmail) do it. A Force Touch press arrives as a pressure event, which can't start
    /// a drag, so a mouse-down at the pointer stands in for it.
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame else { return }
        if message.name == "cxTheme" {
            let body = message.body as? [String: Any] ?? [:]
            let appearance = body["appearance"] as? String
            let ground = body["ground"] as? String
            applyTheme(appearance: appearance, ground: ground)
            UserDefaults.standard.set(appearance, forKey: "themeAppearance")
            UserDefaults.standard.set(ground, forKey: "themeGround")
            return
        }
        guard message.name == "cxDrag" else { return }
        if (message.body as? [String: Any])?["double"] as? Bool == true {
            titleBarDoubleClick()
            return
        }
        guard var event = NSApp.currentEvent else { return }
        if event.type == .pressure, let down = NSEvent.mouseEvent(
            with: .leftMouseDown,
            location: window.convertPoint(fromScreen: NSEvent.mouseLocation),
            modifierFlags: event.modifierFlags, timestamp: event.timestamp,
            windowNumber: window.windowNumber, context: nil, eventNumber: 0,
            clickCount: 1, pressure: 1
        ) {
            event = down
        }
        guard [.leftMouseDown, .leftMouseDragged].contains(event.type) else { return }
        window.performDrag(with: event)
    }

    /// Light or dark (nil: follow the Mac) for the window, its sheets and menus; the board's ground behind it.
    private func applyTheme(appearance: String?, ground: String?) {
        let chosen: NSAppearance? = switch appearance {
        case "dark": NSAppearance(named: .darkAqua)
        case "light": NSAppearance(named: .aqua)
        default: nil
        }
        NSApp.appearance = chosen
        window.appearance = chosen
        let color = ground.flatMap(Self.color(hex:)) ?? NSColor.windowBackgroundColor
        window.backgroundColor = color
        window.contentView?.layer?.backgroundColor = color.cgColor
        webView.underPageBackgroundColor = color
    }

    private static func color(hex: String) -> NSColor? {
        let digits = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        guard digits.count == 6, let value = UInt32(digits, radix: 16) else { return nil }
        return NSColor(
            srgbRed: CGFloat((value >> 16) & 0xFF) / 255,
            green: CGFloat((value >> 8) & 0xFF) / 255,
            blue: CGFloat(value & 0xFF) / 255,
            alpha: 1
        )
    }

    /// A double-click on the title band does what Desktop & Dock says a title bar's does.
    private func titleBarDoubleClick() {
        let defaults = UserDefaults.standard
        switch defaults.string(forKey: "AppleActionOnDoubleClick") {
        case "None":
            return
        case "Minimize":
            window.performMiniaturize(nil)
        case nil where defaults.bool(forKey: "AppleMiniaturizeOnDoubleClick"):
            window.performMiniaturize(nil)
        default:
            window.performZoom(nil)
        }
    }

    // MARK: Finder drops → the page

    private func handOver(_ files: [URL], at point: CGPoint) {
        let paths = files.map(\.path)
        guard let json = try? JSONSerialization.data(withJSONObject: ["paths": paths, "x": point.x, "y": point.y]),
              let arg = String(data: json, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.cxboardsNativeDrop ? window.cxboardsNativeDrop(\(arg)) : false") { result, _ in
            if (result as? Bool) == false {
                NSSound.beep()  // no board open to drop onto
            }
        }
    }

    // MARK: Navigation

    private func openOutside(_ url: URL) {
        if selfTestArgs != nil { openedOutside.append(url.absoluteString) } else { NSWorkspace.shared.open(url) }
    }

    private func isOurs(_ url: URL) -> Bool {
        (url.host == "127.0.0.1" || url.host == "localhost") && url.port == baseURL.port
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else { return decisionHandler(.cancel) }
        if navigationAction.shouldPerformDownload { return decisionHandler(.download) }
        let mainFrame = navigationAction.targetFrame?.isMainFrame ?? true
        // Players (YouTube, Spotify…) load in frames; leaving the board in the main frame opens the browser.
        if mainFrame, !isOurs(url), url.scheme == "http" || url.scheme == "https" || url.scheme == "mailto" {
            openOutside(url)
            return decisionHandler(.cancel)
        }
        if mainFrame, isOurs(url), url.path.hasPrefix("/print/") {
            openOutside(url)  // printing (Save as PDF) belongs to a browser's print dialog
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping @MainActor (WKNavigationResponsePolicy) -> Void
    ) {
        let disposition = (navigationResponse.response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Disposition") ?? ""
        if disposition.lowercased().hasPrefix("attachment") || !navigationResponse.canShowMIMEType {
            return decisionHandler(.download)
        }
        decisionHandler(.allow)
    }

    /// window.open / target=_blank: the browser for anything outside, this window for our own pages.
    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url {
            if isOurs(url) && !url.path.hasPrefix("/print/") {
                webView.load(URLRequest(url: url))
            } else {
                openOutside(url)
            }
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        status.isHidden = true
        if selfTestArgs != nil, !selfTestStarted {
            selfTestStarted = true
            runSelfTest()
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    // MARK: Downloads (exports: Markdown, Word, ZIP, PNG)

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping @MainActor (URL?) -> Void
    ) {
        let folder = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let name = suggestedFilename.isEmpty ? "board" : suggestedFilename
        var target = folder.appendingPathComponent(name)
        let stem = target.deletingPathExtension().lastPathComponent
        let ext = target.pathExtension
        var n = 2
        while FileManager.default.fileExists(atPath: target.path) {
            target = folder.appendingPathComponent(ext.isEmpty ? "\(stem) \(n)" : "\(stem) \(n).\(ext)")
            n += 1
        }
        downloadTargets[ObjectIdentifier(download)] = target
        completionHandler(target)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let target = downloadTargets.removeValue(forKey: ObjectIdentifier(download)) else { return }
        finishedDownloads.append(target)
        // Bounce the Downloads stack, as a browser would.
        DistributedNotificationCenter.default().post(name: .init("com.apple.DownloadFileFinished"), object: target.path)
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloadTargets.removeValue(forKey: ObjectIdentifier(download))
        let alert = NSAlert(error: error)
        alert.beginSheetModal(for: window)
    }

    // MARK: alert / confirm / prompt

    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor () -> Void
    ) {
        if selfTestArgs != nil { return completionHandler() }
        let alert = NSAlert()
        alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor (Bool) -> Void
    ) {
        if selfTestArgs != nil { return completionHandler(true) }
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptTextInputPanelWithPrompt prompt: String,
        defaultText: String?,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor (String?) -> Void
    ) {
        if selfTestArgs != nil { return completionHandler(defaultText) }
        let alert = NSAlert()
        alert.messageText = prompt
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(string: defaultText ?? "")
        field.frame = NSRect(x: 0, y: 0, width: 300, height: 24)
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: window) { response in
            completionHandler(response == .alertFirstButtonReturn ? field.stringValue : nil)
        }
    }

    // MARK: Self-test

    private func sleep(_ seconds: Double) async {
        try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
    }

    private func js(_ source: String) async -> Any? {
        try? await webView.evaluateJavaScript(source)
    }

    private func boardCards(_ board: String) async -> [[String: Any]] {
        let url = baseURL.appendingPathComponent("api/boards/\(board)")
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [] }
        return json["cards"] as? [[String: Any]] ?? []
    }

    private func runSelfTest() {
        guard let args = selfTestArgs else { return }
        let board = args[0]
        let dropPath = args[1]
        Task { @MainActor in
            var results: [String: Any] = ["server": true]
            await sleep(2.0)  // let the board mount
            results["drop_bridge"] = (await js("typeof window.cxboardsNativeDrop")) as? String == "function"
            results["borderless_page"] = (await js(
                "document.documentElement.classList.contains('native') && !!window.webkit.messageHandlers.cxDrag"
            )) as? Bool == true
            results["borderless_window"] = window.titlebarAppearsTransparent && window.styleMask.contains(.fullSizeContentView)
            results["theme_bridge"] = (await js("!!window.webkit.messageHandlers.cxTheme")) as? Bool == true
            results["prompt"] = (await js("prompt('Label', 'from-selftest')")) as? String == "from-selftest"
            results["confirm"] = (await js("confirm('ok?')")) as? Bool == true

            // The sidebar. A right-click there is the page's, so WebKit's own menu never shows; unpinned
            // (⌘\) it floats clear of the traffic lights, and File ▸ New Board still reaches it while it's
            // away. Chris's pin and width are put back afterwards.
            _ = await js("""
            window.__keep = { pin: localStorage.getItem('cxboards.sidebar'), w: localStorage.getItem('cxboards.side-w') };
            window.__menu = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 60, clientY: innerHeight - 140 });
            document.querySelector('aside.sidebar').dispatchEvent(window.__menu); true
            """)
            await sleep(0.3)
            results["sidebar_right_click"] = (await js("""
            window.__menu.defaultPrevented && [...document.querySelectorAll('.menu .menu-item')].some((b) => b.textContent === 'New folder')
            """)) as? Bool == true
            _ = await js("window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); true")
            _ = await js("window.dispatchEvent(new KeyboardEvent('keydown', { key: '\\\\', metaKey: true })); true")
            await sleep(0.4)
            results["sidebar_floats_clear_of_the_lights"] = (await js("""
            (() => { const aside = document.querySelector('aside.sidebar');
              return document.querySelector('.app').classList.contains('side-unpinned') && aside.inert
                && parseFloat(getComputedStyle(document.querySelector('.topbar')).paddingLeft) >= 80
                && parseFloat(getComputedStyle(aside).paddingTop) >= 30 })()
            """)) as? Bool == true
            newBoard()
            await sleep(0.4)
            results["new_board_while_sidebar_away"] = (await js("""
            (() => { const open = (document.querySelector('.dialog h2')?.textContent ?? '') === 'New board';
              document.querySelector('.dialog footer .ghost')?.click(); return open })()
            """)) as? Bool == true
            _ = await js("window.dispatchEvent(new KeyboardEvent('keydown', { key: '\\\\', metaKey: true })); true")
            await sleep(0.3)
            _ = await js("""
            for (const [key, value] of [['cxboards.sidebar', window.__keep.pin], ['cxboards.side-w', window.__keep.w]])
              value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); true
            """)

            // A native Finder drop in the middle of the window.
            let middle = CGPoint(x: webView.bounds.midX, y: webView.bounds.midY)
            handOver([URL(fileURLWithPath: dropPath)], at: middle)
            var dropped = false
            for _ in 0..<20 {
                await sleep(0.3)
                let cards = await boardCards(board)
                if cards.contains(where: { (($0["data"] as? [String: Any])?["path"] as? String) == dropPath }) {
                    dropped = true
                    break
                }
            }
            results["native_drop_points_at_the_file"] = dropped

            // An export download lands in ~/Downloads.
            _ = await js("""
            (() => { const a = document.createElement('a'); a.href = '/api/boards/\(board)/export.md';
              a.download = ''; document.body.appendChild(a); a.click(); a.remove(); return true })()
            """)
            for _ in 0..<20 where finishedDownloads.isEmpty { await sleep(0.3) }
            results["download"] = finishedDownloads.first?.path ?? false
            for file in finishedDownloads { try? FileManager.default.removeItem(at: file) }

            // Outside links leave the app: window.open and a main-frame navigation.
            _ = await js("window.open('https://example.com/from-window-open', '_blank'); true")
            _ = await js("location.href = 'https://example.org/from-navigation'; true")
            await sleep(1.0)
            results["outside_links"] = openedOutside
            results["stayed_on_board"] = webView.url?.path == "/b/\(board)"
            finishSelfTest(results)
        }
    }

    private func finishSelfTest(_ results: [String: Any]) {
        let checks = ["server", "drop_bridge", "borderless_page", "borderless_window", "theme_bridge", "prompt", "confirm",
                      "sidebar_right_click", "sidebar_floats_clear_of_the_lights", "new_board_while_sidebar_away",
                      "native_drop_points_at_the_file", "stayed_on_board"]
        var ok = checks.allSatisfy { results[$0] as? Bool == true }
        ok = ok && results["download"] is String && (results["outside_links"] as? [String])?.count == 2
        var out = results
        out["ok"] = ok
        if let data = try? JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys]),
           let text = String(data: data, encoding: .utf8) {
            print(text)
        }
        exit(ok ? 0 : 1)
    }

    // MARK: Menu

    @objc private func newBoard() {
        webView.evaluateJavaScript("document.querySelector('.new-board')?.click()")
    }

    @objc private func openSettings() {
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('cxboards:open-settings'))")
    }

    @objc private func reloadPage() {
        if ready { webView.reload() } else { retry() }
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: NSString(string: "~/Library/Logs/cxboards.log").expandingTildeInPath))
    }

    @objc private func openInBrowser() {
        NSWorkspace.shared.open(webView.url ?? baseURL)
    }

    private func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let app = NSMenu()
        app.addItem(withTitle: "About CXBoards", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Settings…", action: #selector(openSettings), keyEquivalent: ",").target = self
        app.addItem(.separator())
        app.addItem(withTitle: "Hide CXBoards", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let others = app.addItem(withTitle: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        others.keyEquivalentModifierMask = [.command, .option]
        app.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Quit CXBoards", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = app
        main.addItem(appItem)

        let fileItem = NSMenuItem()
        let file = NSMenu(title: "File")
        file.addItem(withTitle: "New Board…", action: #selector(newBoard), keyEquivalent: "n").target = self
        file.addItem(withTitle: "Open in Browser", action: #selector(openInBrowser), keyEquivalent: "").target = self
        file.addItem(.separator())
        file.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileItem.submenu = file
        main.addItem(fileItem)

        // Standard edit actions so text fields get cut/copy/paste/undo. On the canvas the page's own
        // ⌘Z/⌘C/⌘V handlers run first (the web view sees key equivalents before the menu does).
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let viewItem = NSMenuItem()
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reloadPage), keyEquivalent: "r").target = self
        let full = view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        full.keyEquivalentModifierMask = [.command, .control]
        view.addItem(.separator())
        view.addItem(withTitle: "Server Log", action: #selector(openLog), keyEquivalent: "").target = self
        viewItem.submenu = view
        main.addItem(viewItem)

        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(.separator())
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        windowItem.submenu = windowMenu
        main.addItem(windowItem)
        NSApp.windowsMenu = windowMenu

        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.activate(ignoringOtherApps: true)
app.run()
