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

import AVFoundation
import Foundation
import Speech

let SAMPLE_RATE = 16000.0

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
        die("speech recognition not authorized (\(status.rawValue)). "
            + "System Settings > Privacy & Security > Speech Recognition.", 2)
    }
}

func recognizer() -> SFSpeechRecognizer {
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
    return rec
}

/// Transcribe one finished buffer. Synchronous on purpose: the caller has already
/// decided this audio is complete, and Flow's decode worker is the thing that owns
/// concurrency.
func transcribe(_ rec: SFSpeechRecognizer, _ samples: [Float]) -> String {
    guard !samples.isEmpty else { return "" }
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                               sampleRate: SAMPLE_RATE, channels: 1, interleaved: false)!
    guard let buffer = AVAudioPCMBuffer(pcmFormat: format,
                                        frameCapacity: AVAudioFrameCount(samples.count))
    else { return "" }
    buffer.frameLength = AVAudioFrameCount(samples.count)
    samples.withUnsafeBufferPointer { src in
        buffer.floatChannelData!.pointee.update(from: src.baseAddress!,
                                                count: samples.count)
    }

    let request = SFSpeechAudioBufferRecognitionRequest()
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false
    // Punctuation is the difference between dictation and a transcript. Flow's own
    // cleaner assumes sentences.
    if #available(macOS 13.0, *) { request.addsPunctuation = true }
    request.append(buffer)
    request.endAudio()

    let gate = DispatchSemaphore(value: 0)
    var text = ""
    let task = rec.recognitionTask(with: request) { result, error in
        if let result = result, result.isFinal {
            text = result.bestTranscription.formattedString
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
    if gate.wait(timeout: .now() + 30) == .timedOut { task.cancel() }
    return text
}

func serve(_ rec: SFSpeechRecognizer) {
    let input = FileHandle.standardInput
    let output = FileHandle.standardOutput
    while true {
        let header = input.readData(ofLength: 4)
        if header.count < 4 { return }  // stdin closed: Flow is gone, so are we
        let count = header.withUnsafeBytes { $0.load(as: UInt32.self).littleEndian }
        var payload = Data()
        while payload.count < Int(count) * 4 {
            let chunk = input.readData(ofLength: Int(count) * 4 - payload.count)
            if chunk.isEmpty { return }
            payload.append(chunk)
        }
        let samples = payload.withUnsafeBytes { raw -> [Float] in
            Array(raw.bindMemory(to: Float.self))
        }
        let line = transcribe(rec, samples).replacingOccurrences(of: "\n", with: " ")
        output.write((line + "\n").data(using: .utf8)!)
    }
}

func fromFile(_ path: String, _ rec: SFSpeechRecognizer) {
    guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
        die("cannot read \(path)")
    }
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                               sampleRate: SAMPLE_RATE, channels: 1, interleaved: false)!
    guard let converter = AVAudioConverter(from: file.processingFormat, to: format),
          let source = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                        frameCapacity: AVAudioFrameCount(file.length))
    else { die("cannot convert \(path) to 16 kHz mono") }
    try? file.read(into: source)
    let frames = AVAudioFrameCount(Double(source.frameLength)
                                   * SAMPLE_RATE / file.processingFormat.sampleRate) + 1024
    guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else {
        die("cannot allocate output buffer")
    }
    var done = false
    var error: NSError?
    converter.convert(to: out, error: &error) { _, status in
        if done { status.pointee = .noDataNow; return nil }
        done = true
        status.pointee = .haveData
        return source
    }
    if let error = error { die("resample failed: \(error.localizedDescription)") }
    let samples = Array(UnsafeBufferPointer(start: out.floatChannelData![0],
                                            count: Int(out.frameLength)))
    print(transcribe(rec, samples))
}

// -- main ------------------------------------------------------------------

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "--probe" {
    // What the Python side calls to decide whether this engine exists at all, before
    // it commits a session to it. Authorization included, because an engine the user
    // has not allowed is not an engine that works.
    authorize()
    _ = recognizer()
    print("ok")
    exit(0)
}
authorize()
let rec = recognizer()
if args.count == 2 && args[0] == "--file" {
    fromFile(args[1], rec)
} else if args.isEmpty {
    serve(rec)
} else {
    die("usage: flow-stt [--probe | --file AUDIO]")
}
