//  flow_stt.swift — Flow's macOS decoder, as a process Flow talks to over a pipe.
//
//  Why a separate binary rather than a Python binding: Flow's dependency budget is
//  three (R16) and PyObjC is not one of them. Flow already shells out to `codex` and
//  `claude`, so a subprocess that reads audio and writes text is a shape the app
//  already has — and it keeps every Objective-C API on the far side of a pipe, where a
//  crash is an exit code rather than a dead interpreter.
//
//  Why it matters: the CT2 weights faster-whisper needs exist on HuggingFace and
//  nowhere else official — SYSTRAN's GitHub ships source only. On a network that blocks
//  huggingface.co that leaves copying files by hand. Apple's recogniser needs no
//  download at all: the models belong to the OS.
//
//  Build:
//      swiftc -O -o flow-stt native/flow_stt.swift
//
//  Two ways to run it, and the first exists so the second is worth doing:
//
//      flow-stt --file some.wav     one transcript to stdout, then exit.
//                                   Judge Apple's quality on your own voice before
//                                   anybody wires this into a dictation loop.
//
//      flow-stt                     serve: repeatedly read a length-prefixed block of
//                                   float32 mono 16 kHz PCM from stdin and write one
//                                   line of transcript to stdout. Stays warm, because
//                                   a process per utterance would cost more than the
//                                   decode.
//
//  The framing is deliberately dull: 4 bytes little-endian sample count, then that many
//  float32 samples. One line of UTF-8 back per block, newline-terminated, empty line for
//  silence. Anything this cannot do goes to stderr and exits non-zero, so the Python
//  side can report a reason rather than a hang.
//
//  Three things here are load-bearing and easy to undo by tidying:
//
//    * **`@main`, not top-level code.** Swift allows statements at file scope only in a
//      file called `main.swift`. This one is not, so the entry point is a type.
//    * **The recogniser gets its own queue.** Its callbacks default to the main queue,
//      and `transcribe` blocks the calling thread waiting for one — on the main thread
//      that is a deadlock, not a slow decode.
//    * **Every read out of `Data` is unaligned.** `Data` gives no alignment guarantee
//      and `load(as:)` requires one; the aligned form crashes on some buffers and not
//      others, which is the worst way to find out.

import AVFoundation
import Foundation
import Speech

let SAMPLE_RATE = 16000.0
let DECODE_TIMEOUT: TimeInterval = 30

func die(_ message: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write(("flow-stt: " + message + "\n").data(using: .utf8)!)
    exit(code)
}

/// Ask once, block until the user has answered, and treat every non-authorized answer
/// the same. The prompt is attributed to whatever launched this — a terminal, usually —
/// which is the known wart of running unbundled and is documented on the Python side.
func authorize() {
    let gate = DispatchSemaphore(value: 0)
    var status: SFSpeechRecognizerAuthorizationStatus = .notDetermined
    SFSpeechRecognizer.requestAuthorization { got in
        status = got
        gate.signal()
    }
    gate.wait()
    guard status == .authorized else {
        die("speech recognition not authorized (status \(status.rawValue)). "
            + "System Settings > Privacy & Security > Speech Recognition.", 2)
    }
}

func makeRecognizer() -> SFSpeechRecognizer {
    guard let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) else {
        die("no recognizer for en-US on this machine", 3)
    }
    guard rec.isAvailable else { die("recognizer exists but is not available", 4) }
    // The whole point. Without this the audio goes to Apple's servers, which is a
    // different product from the one Flow is: local by construction.
    guard rec.supportsOnDeviceRecognition else {
        die("on-device recognition unavailable — enable Dictation in System Settings "
            + "so macOS downloads the offline model", 5)
    }
    // Off the main queue, deliberately. `transcribe` waits on a semaphore for the
    // result, and a recogniser delivering that result *to the thread doing the waiting*
    // is a deadlock. This is the line that makes the blocking call safe.
    rec.queue = OperationQueue()
    return rec
}

/// Transcribe one finished buffer. Synchronous on purpose: the caller has already
/// decided this audio is complete, and Flow's decode worker owns concurrency.
func transcribe(_ rec: SFSpeechRecognizer, _ samples: [Float]) -> String {
    guard !samples.isEmpty else { return "" }
    guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                     sampleRate: SAMPLE_RATE,
                                     channels: 1, interleaved: false),
          let buffer = AVAudioPCMBuffer(pcmFormat: format,
                                        frameCapacity: AVAudioFrameCount(samples.count)),
          let channel = buffer.floatChannelData
    else { return "" }
    buffer.frameLength = AVAudioFrameCount(samples.count)
    samples.withUnsafeBufferPointer { src in
        if let base = src.baseAddress {
            memcpy(channel[0], base, samples.count * MemoryLayout<Float>.size)
        }
    }

    let request = SFSpeechAudioBufferRecognitionRequest()
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false
    // Punctuation is the difference between dictation and a transcript; Flow's cleaner
    // assumes sentences.
    if #available(macOS 13.0, *) { request.addsPunctuation = true }
    request.append(buffer)
    request.endAudio()

    let gate = DispatchSemaphore(value: 0)
    // Written from the recogniser's queue and read from this one, so the handoff is
    // guarded rather than assumed.
    let lock = NSLock()
    var text = ""
    let task = rec.recognitionTask(with: request) { result, error in
        if let result = result, result.isFinal {
            lock.lock(); text = result.bestTranscription.formattedString; lock.unlock()
            gate.signal()
        } else if error != nil {
            // A recogniser that heard nothing reports an error rather than an empty
            // result. Silence is not a failure here — Flow's gate already decided this
            // block was speech, and an empty line is how "nothing said" is spelled.
            gate.signal()
        }
    }
    // Bounded, because a recogniser that never calls back would otherwise hang the
    // decode worker and, through it, the draft the user is waiting for.
    if gate.wait(timeout: .now() + DECODE_TIMEOUT) == .timedOut { task.cancel() }
    lock.lock(); defer { lock.unlock() }
    return text
}

/// Read exactly `count` bytes, or nil if the pipe closed first.
func readExactly(_ handle: FileHandle, _ count: Int) -> Data? {
    var out = Data()
    while out.count < count {
        let chunk = handle.readData(ofLength: count - out.count)
        if chunk.isEmpty { return nil }
        out.append(chunk)
    }
    return out
}

func serve(_ rec: SFSpeechRecognizer) {
    let input = FileHandle.standardInput
    let output = FileHandle.standardOutput
    while true {
        guard let header = readExactly(input, 4) else { return }  // Flow is gone
        // Unaligned on purpose: `Data`'s backing store carries no alignment guarantee,
        // and the aligned `load(as:)` traps on buffers that happen not to be.
        let count = Int(header.withUnsafeBytes {
            $0.loadUnaligned(fromByteOffset: 0, as: UInt32.self).littleEndian
        })
        guard count > 0, count < 30 * Int(SAMPLE_RATE) * 60 else { return }
        guard let payload = readExactly(input, count * 4) else { return }
        var samples = [Float](repeating: 0, count: count)
        samples.withUnsafeMutableBytes { dst in
            payload.copyBytes(to: dst.bindMemory(to: UInt8.self))
        }
        let line = transcribe(rec, samples).replacingOccurrences(of: "\n", with: " ")
        if let data = (line + "\n").data(using: .utf8) { output.write(data) }
    }
}

func fromFile(_ path: String, _ rec: SFSpeechRecognizer) {
    guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
        die("cannot read \(path)")
    }
    guard let target = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                     sampleRate: SAMPLE_RATE,
                                     channels: 1, interleaved: false),
          let converter = AVAudioConverter(from: file.processingFormat, to: target),
          let source = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                        frameCapacity: AVAudioFrameCount(file.length))
    else { die("cannot convert \(path) to 16 kHz mono") }
    do { try file.read(into: source) } catch { die("read failed: \(error)") }

    let ratio = SAMPLE_RATE / file.processingFormat.sampleRate
    let frames = AVAudioFrameCount(Double(source.frameLength) * ratio) + 4096
    guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: frames) else {
        die("cannot allocate output buffer")
    }
    var supplied = false
    var error: NSError?
    converter.convert(to: out, error: &error) { _, status in
        if supplied {
            status.pointee = .endOfStream
            return nil
        }
        supplied = true
        status.pointee = .haveData
        return source
    }
    if let error = error { die("resample failed: \(error.localizedDescription)") }
    guard let channel = out.floatChannelData else { die("no samples after resample") }
    let samples = Array(UnsafeBufferPointer(start: channel[0],
                                            count: Int(out.frameLength)))
    print(transcribe(rec, samples))
}

enum Mode {
    case probe
    case file(String)
    case serve
}

@main
struct FlowSTT {
    /// **Arguments are checked before anything is asked of the user.** A typo must not
    /// raise a permission prompt, and CI has to be able to reach the usage line on a
    /// runner where no permission could ever be granted — which is the only way the
    /// compile leg can prove this binary links and runs at all.
    static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        let mode: Mode
        if args == ["--probe"] {
            mode = .probe
        } else if args.count == 2 && args[0] == "--file" {
            mode = .file(args[1])
        } else if args.isEmpty {
            mode = .serve
        } else {
            die("usage: flow-stt [--probe | --file AUDIO]")
        }

        // Everything past here needs a recogniser, and a recogniser needs consent.
        authorize()
        let rec = makeRecognizer()
        switch mode {
        case .probe:
            // What the Python side calls to decide whether this engine exists at all,
            // before it commits a session to it. Reaching this line is the answer.
            print("ok")
        case .file(let path):
            fromFile(path, rec)
        case .serve:
            serve(rec)
        }
    }
}
