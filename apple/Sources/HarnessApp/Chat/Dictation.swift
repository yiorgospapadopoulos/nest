import AVFoundation
import HarnessKit
import Observation
import Speech

/// Speech to text into one composer at a time. It uses Apple's on-device SpeechAnalyzer
/// with SpeechTranscriber (installing the language model on first use), and the older
/// SFSpeechRecognizer when that is not available. In-progress (volatile) text shows
/// lighter after the composer's text until a final result replaces it.
@MainActor @Observable
final class Dictation {
    /// The chat whose composer is listening.
    private(set) var activeChat: String?
    /// The chat whose dictation is getting ready, with a short line about it.
    private(set) var preparing: (chat: String, text: String)?

    @ObservationIgnored private var engine: (any SpeechEngine)?
    @ObservationIgnored private var listener: Task<Void, Never>?
    @ObservationIgnored private weak var draft: ComposerDraft?
    /// Bumped on every start and cancel, so late results of an older run are dropped.
    @ObservationIgnored private var generation = 0

    /// The line to show under a composer while its dictation gets ready.
    func status(for chat: String) -> String? {
        preparing?.chat == chat ? preparing?.text : nil
    }

    /// Starts listening for `chat`, or stops when it is already listening (keeping what
    /// was heard). `terms` help recognition with the chat's vocabulary. Returns a short
    /// hint when dictation cannot start.
    func toggle(for chat: String, draft: ComposerDraft, terms: [String]) async -> String? {
        if activeChat == chat {
            finish()
            return nil
        }
        if preparing?.chat == chat {
            cancel()
            return nil
        }
        cancel()
        let info = Bundle.main.infoDictionary ?? [:]
        guard info["NSSpeechRecognitionUsageDescription"] != nil,
            info["NSMicrophoneUsageDescription"] != nil
        else { return "Dictation works in the bundled app (make app)" }
        let run = generation
        preparing = (chat, "Getting dictation ready")
        if let refusal = await DictationAccess.request().hint {
            endPreparing(run)
            return refusal
        }
        guard run == generation else { return nil }
        let engine: any SpeechEngine
        do {
            engine = try await makeEngine(terms: terms, run: run)
            guard run == generation else {
                await engine.stop(commit: false)
                return nil
            }
            try await engine.start()
        } catch {
            endPreparing(run)
            return (error as? DictationError)?.hint
                ?? "Dictation could not start: \(error.localizedDescription)"
        }
        guard run == generation else {
            await engine.stop(commit: false)
            return nil
        }
        preparing = nil
        self.engine = engine
        self.draft = draft
        activeChat = chat
        listener = Task { [weak self] in
            var buffer = DictationBuffer(text: draft.text)
            do {
                for try await piece in engine.transcripts {
                    guard let self, self.generation == run else { return }
                    buffer.apply(piece.text, isFinal: piece.isFinal, current: draft.text)
                    draft.text = buffer.committed
                    draft.volatile = buffer.volatileSuffix
                }
            } catch {
                // Recognition ended early; keep what was heard.
            }
            guard let self, self.generation == run else { return }
            buffer.commit(current: draft.text)
            draft.text = buffer.committed
            draft.volatile = ""
            self.engine = nil
            self.activeChat = nil
        }
        return nil
    }

    /// Stops listening; what is still being recognized is finalized into the text.
    func finish() {
        guard let engine else {
            cancel()
            return
        }
        self.engine = nil
        activeChat = nil
        Task { await engine.stop(commit: true) }
    }

    /// Stops at once and drops what is still being recognized, as when sending.
    func cancel() {
        generation += 1
        listener?.cancel()
        listener = nil
        if let engine {
            Task { await engine.stop(commit: false) }
        }
        engine = nil
        draft?.volatile = ""
        draft = nil
        activeChat = nil
        preparing = nil
    }

    private func endPreparing(_ run: Int) {
        if run == generation {
            preparing = nil
        }
    }

    /// SpeechAnalyzer when this Mac has a transcriber for the user's language, else
    /// SFSpeechRecognizer.
    private func makeEngine(terms: [String], run: Int) async throws -> any SpeechEngine {
        if SpeechTranscriber.isAvailable,
            let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale.current)
        {
            let transcriber = SpeechTranscriber(locale: locale, preset: .progressiveTranscription)
            do {
                try await installModel(for: transcriber, locale: locale, run: run)
                return try await AnalyzerEngine.make(transcriber: transcriber, terms: terms)
            } catch {
                // The model could not be installed or prepared: use the older recognizer.
            }
        }
        guard let recognizer = SFSpeechRecognizer(), recognizer.isAvailable else {
            throw DictationError.unavailable
        }
        return RecognizerEngine(recognizer: recognizer, terms: terms)
    }

    /// Downloads the language model the first time, with its progress under the composer.
    private func installModel(for transcriber: SpeechTranscriber, locale: Locale, run: Int)
        async throws
    {
        guard
            let request = try await AssetInventory.assetInstallationRequest(supporting: [
                transcriber
            ])
        else { return }
        let language = Locale.current.localizedString(forIdentifier: locale.identifier)
        let what = language.map { "the \($0) speech model" } ?? "the speech model"
        let poll = Task { [weak self] in
            while !Task.isCancelled {
                let percent = Int((request.progress.fractionCompleted * 100).rounded())
                if let self, run == self.generation, let chat = self.preparing?.chat {
                    self.preparing = (chat, "Downloading \(what) (first use), \(percent)%")
                }
                try? await Task.sleep(for: .milliseconds(250))
            }
        }
        defer { poll.cancel() }
        try await request.downloadAndInstall()
    }
}

enum DictationError: Error {
    case unavailable
    case noInput

    var hint: String {
        switch self {
        case .unavailable: "Dictation is not available right now"
        case .noInput: "No microphone input is available"
        }
    }
}

/// A recognition result: volatile text replaces the previous guess, final text stays.
struct SpeechPiece: Sendable {
    let text: String
    let isFinal: Bool
}

/// An audio engine feeding a recognizer. Started and stopped by `Dictation` on the main
/// actor; the audio tap and recognition callbacks run on system threads, so they are
/// `@Sendable` and only touch the engine's own state and its stream.
protocol SpeechEngine: AnyObject, Sendable {
    /// Ends when recognition finishes, after `stop`.
    var transcripts: AsyncThrowingStream<SpeechPiece, any Error> { get }
    func start() async throws
    /// Stops the microphone; `commit` lets the last words be finalized first.
    func stop(commit: Bool) async
}

/// SpeechAnalyzer with a SpeechTranscriber; microphone audio is converted to the
/// analyzer's format and streamed into its input sequence.
private final class AnalyzerEngine: SpeechEngine, @unchecked Sendable {
    let transcripts: AsyncThrowingStream<SpeechPiece, any Error>
    private let output: AsyncThrowingStream<SpeechPiece, any Error>.Continuation
    private let input: AsyncStream<AnalyzerInput>
    private let feed: AsyncStream<AnalyzerInput>.Continuation
    private let transcriber: SpeechTranscriber
    private let analyzer: SpeechAnalyzer
    private let format: AVAudioFormat
    private let audio = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var results: Task<Void, Never>?
    private var tapped = false

    private init(transcriber: SpeechTranscriber, analyzer: SpeechAnalyzer, format: AVAudioFormat) {
        self.transcriber = transcriber
        self.analyzer = analyzer
        self.format = format
        (transcripts, output) = AsyncThrowingStream.makeStream()
        (input, feed) = AsyncStream.makeStream()
    }

    /// Prepares the analyzer for the transcriber's audio format, with the chat's words as
    /// contextual strings.
    static func make(transcriber: SpeechTranscriber, terms: [String]) async throws
        -> AnalyzerEngine
    {
        guard
            let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [
                transcriber
            ])
        else { throw DictationError.unavailable }
        let analyzer = SpeechAnalyzer(
            modules: [transcriber],
            options: SpeechAnalyzer.Options(priority: .userInitiated, modelRetention: .lingering))
        try await analyzer.prepareToAnalyze(in: format)
        if !terms.isEmpty {
            let context = AnalysisContext()
            context.contextualStrings[.general] = terms
            // Contextual strings are a hint; a transcriber that ignores them still works.
            try? await analyzer.setContext(context)
        }
        return AnalyzerEngine(transcriber: transcriber, analyzer: analyzer, format: format)
    }

    func start() async throws {
        let node = audio.inputNode
        let microphone = node.outputFormat(forBus: 0)
        guard microphone.channelCount > 0, microphone.sampleRate > 0,
            let converter = AVAudioConverter(from: microphone, to: format)
        else { throw DictationError.noInput }
        self.converter = converter
        results = Task { [transcriber, output] in
            do {
                for try await result in transcriber.results {
                    output.yield(
                        SpeechPiece(text: String(result.text.characters), isFinal: result.isFinal))
                }
                output.finish()
            } catch {
                output.finish(throwing: error)
            }
        }
        try await analyzer.start(inputSequence: input)
        // Runs on the audio thread: converts and hands the buffer to the analyzer.
        node.installTap(onBus: 0, bufferSize: 4096, format: microphone) {
            @Sendable [weak self] buffer, _ in
            self?.convert(buffer)
        }
        tapped = true
        audio.prepare()
        do {
            try audio.start()
        } catch {
            await stop(commit: false)
            throw error
        }
    }

    func stop(commit: Bool) async {
        if audio.isRunning {
            audio.stop()
        }
        if tapped {
            audio.inputNode.removeTap(onBus: 0)
            tapped = false
        }
        feed.finish()
        // Finalizing ends the transcriber's results, which finishes the stream.
        if commit, (try? await analyzer.finalizeAndFinishThroughEndOfInput()) != nil {
            return
        }
        await analyzer.cancelAndFinishNow()
        results?.cancel()
        output.finish()
    }

    private func convert(_ buffer: AVAudioPCMBuffer) {
        guard let converter, buffer.frameLength > 0 else { return }
        let ratio = format.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount((Double(buffer.frameLength) * ratio).rounded(.up)) + 32
        guard let converted = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else {
            return
        }
        let source = OneBuffer(buffer)
        var error: NSError?
        let status = converter.convert(to: converted, error: &error) { _, status in
            source.next(status)
        }
        guard status != .error, converted.frameLength > 0 else { return }
        feed.yield(AnalyzerInput(buffer: converted))
    }
}

/// Hands one buffer to an AVAudioConverter, then reports that no more data is ready, so
/// the converter keeps its state for the next tap buffer.
private final class OneBuffer: @unchecked Sendable {
    private var buffer: AVAudioPCMBuffer?

    init(_ buffer: AVAudioPCMBuffer) {
        self.buffer = buffer
    }

    func next(_ status: UnsafeMutablePointer<AVAudioConverterInputStatus>) -> AVAudioBuffer? {
        guard let buffer else {
            status.pointee = .noDataNow
            return nil
        }
        self.buffer = nil
        status.pointee = .haveData
        return buffer
    }
}

/// SFSpeechRecognizer, for Macs without a SpeechTranscriber for the user's language.
private final class RecognizerEngine: SpeechEngine, @unchecked Sendable {
    let transcripts: AsyncThrowingStream<SpeechPiece, any Error>
    private let output: AsyncThrowingStream<SpeechPiece, any Error>.Continuation
    private let recognizer: SFSpeechRecognizer
    private let audio = AVAudioEngine()
    private let request = SFSpeechAudioBufferRecognitionRequest()
    private var task: SFSpeechRecognitionTask?
    private var tapped = false

    init(recognizer: SFSpeechRecognizer, terms: [String]) {
        self.recognizer = recognizer
        (transcripts, output) = AsyncThrowingStream.makeStream()
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        request.contextualStrings = terms
    }

    func start() async throws {
        let input = audio.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.channelCount > 0, format.sampleRate > 0 else {
            throw DictationError.noInput
        }
        // Runs on the audio thread; appending to the request is safe from there.
        input.installTap(onBus: 0, bufferSize: 1024, format: format) {
            @Sendable [weak self] buffer, _ in
            self?.request.append(buffer)
        }
        tapped = true
        audio.prepare()
        do {
            try audio.start()
        } catch {
            await stop(commit: false)
            throw error
        }
        // Partial results carry everything heard so far, so each one is the new guess.
        task = recognizer.recognitionTask(with: request) { @Sendable [output] result, error in
            if let result {
                output.yield(
                    SpeechPiece(
                        text: result.bestTranscription.formattedString, isFinal: result.isFinal))
                if result.isFinal {
                    output.finish()
                }
            } else if let error {
                output.finish(throwing: error)
            }
        }
    }

    func stop(commit: Bool) async {
        if audio.isRunning {
            audio.stop()
        }
        if tapped {
            audio.inputNode.removeTap(onBus: 0)
            tapped = false
        }
        request.endAudio()
        if !commit {
            task?.cancel()
            output.finish()
        }
    }
}

/// Speech recognition and microphone permission. Both system prompts call back on a
/// private queue, so nothing here is isolated to the main actor: a main actor closure
/// called there traps at runtime.
enum DictationAccess: Equatable {
    case granted
    case denied(String)
    case restricted(String)

    /// The inline hint when dictation may not run.
    var hint: String? {
        switch self {
        case .granted: nil
        case .denied(let what): "Allow \(what) for Harness in System Settings > Privacy"
        case .restricted(let what): "\(what) is restricted on this Mac"
        }
    }

    nonisolated static func request() async -> DictationAccess {
        switch await speechStatus() {
        case .authorized: break
        case .restricted: return .restricted("Speech Recognition")
        default: return .denied("Speech Recognition")
        }
        switch await microphoneStatus() {
        case .authorized: return .granted
        case .restricted: return .restricted("Microphone")
        default: return .denied("Microphone")
        }
    }

    private nonisolated static func speechStatus() async -> SFSpeechRecognizerAuthorizationStatus {
        let current = SFSpeechRecognizer.authorizationStatus()
        guard current == .notDetermined else { return current }
        return await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { @Sendable status in
                continuation.resume(returning: status)
            }
        }
    }

    private nonisolated static func microphoneStatus() async -> AVAuthorizationStatus {
        let current = AVCaptureDevice.authorizationStatus(for: .audio)
        guard current == .notDetermined else { return current }
        let granted = await withCheckedContinuation { continuation in
            AVCaptureDevice.requestAccess(for: .audio) { @Sendable granted in
                continuation.resume(returning: granted)
            }
        }
        return granted ? .authorized : .denied
    }
}
