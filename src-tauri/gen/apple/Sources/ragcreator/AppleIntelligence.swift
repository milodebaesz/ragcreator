// Apple Intelligence for the "Vraag" screen, exposed to Rust as plain C.
//
// The Rust library cannot link against these functions directly (its cdylib
// build would fail on undefined symbols), so main.mm hands their addresses to
// Rust through rc_register_ai() before the app starts — see src-tauri/src/ai.rs.
//
// Everything runs on the phone: FoundationModels is Apple's on-device model,
// nothing is sent anywhere. Both functions return a malloc'd JSON string that
// Rust frees again through rc_ai_free().

import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

private func json(_ object: [String: Any]) -> UnsafeMutablePointer<CChar>? {
    let data = (try? JSONSerialization.data(withJSONObject: object)) ?? Data("{}".utf8)
    return strdup(String(decoding: data, as: UTF8.self))
}

@_cdecl("rc_ai_free")
public func rc_ai_free(_ pointer: UnsafeMutablePointer<CChar>?) {
    free(pointer)
}

/// {"available": Bool, "reason": String?}
@_cdecl("rc_ai_status")
public func rc_ai_status() -> UnsafeMutablePointer<CChar>? {
    #if canImport(FoundationModels)
    if #available(iOS 26.0, *) {
        switch SystemLanguageModel.default.availability {
        case .available:
            return json(["available": true])
        case .unavailable(.deviceNotEligible):
            return json(["available": false, "reason": "Dit toestel ondersteunt Apple Intelligence niet."])
        case .unavailable(.appleIntelligenceNotEnabled):
            return json(["available": false, "reason": "Zet Apple Intelligence aan in Instellingen."])
        case .unavailable(.modelNotReady):
            return json(["available": false, "reason": "Het taalmodel wordt nog gedownload. Probeer het later opnieuw."])
        case .unavailable:
            return json(["available": false, "reason": "Apple Intelligence is niet beschikbaar."])
        }
    }
    #endif
    return json(["available": false, "reason": "Apple Intelligence vereist iOS 26 of nieuwer."])
}

/// Holds the result across the Task boundary; written once, read after the
/// semaphore, so the unchecked Sendable is sound.
private final class ResultBox: @unchecked Sendable {
    var value: [String: Any] = [:]
}

/// Blocks until the model has answered: {"text": String} or {"error": String}.
///
/// Called from a Rust blocking thread, never the main thread, so waiting on
/// the semaphore does not stall the UI.
@_cdecl("rc_ai_generate")
public func rc_ai_generate(
    _ instructions: UnsafePointer<CChar>,
    _ prompt: UnsafePointer<CChar>,
    _ temperature: Double
) -> UnsafeMutablePointer<CChar>? {
    #if canImport(FoundationModels)
    if #available(iOS 26.0, *) {
        let instructionText = String(cString: instructions)
        let promptText = String(cString: prompt)
        let box = ResultBox()
        let done = DispatchSemaphore(value: 0)

        Task.detached {
            do {
                let session = LanguageModelSession(instructions: instructionText)
                let response = try await session.respond(
                    to: promptText,
                    options: GenerationOptions(temperature: temperature)
                )
                box.value = ["text": response.content]
            } catch let error as LanguageModelSession.GenerationError {
                switch error {
                case .guardrailViolation:
                    box.value = ["error": "Apple Intelligence weigerde deze vraag te beantwoorden."]
                case .exceededContextWindowSize:
                    box.value = ["error": "De vraag met bronnen is te lang voor het taalmodel."]
                case .unsupportedLanguageOrLocale:
                    box.value = ["error": "Deze taal wordt niet ondersteund door het taalmodel."]
                default:
                    box.value = ["error": error.localizedDescription]
                }
            } catch {
                box.value = ["error": error.localizedDescription]
            }
            done.signal()
        }

        done.wait()
        return json(box.value)
    }
    #endif
    return json(["error": "Apple Intelligence vereist iOS 26 of nieuwer."])
}
