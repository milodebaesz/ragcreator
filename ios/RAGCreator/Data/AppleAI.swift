import Foundation
import FoundationModels

/// Apple Intelligence on this device: turning a question into search terms
/// and answering it from the recommendations the search found.
///
/// Each call uses a fresh session, so an earlier answer can never colour the
/// next one. Nothing leaves the phone.
enum AppleAI {
    /// How many sources the model gets: its context window is a few thousand
    /// tokens, and every source also has to fit on screen as a citation.
    static let sourcesForModel = 6
    private static let sourceChars = 700

    static let keywordInstructions = """
    Je zet een klinische vraag om in Engelse zoektermen voor ESC-richtlijnen (European Society of Cardiology).
    Geef 4 tot 10 zoektermen: Engelse medische termen, gangbare afkortingen en synoniemen zoals ze in richtlijnaanbevelingen staan.
    Antwoord alleen met de termen, gescheiden door komma's. Geen uitleg.
    """

    static let answerInstructions = """
    Je helpt een arts aanbevelingen uit ESC-richtlijnen te vinden.
    Beantwoord de vraag uitsluitend met de genummerde bronnen die je krijgt. Gebruik geen eigen kennis.
    Verwijs na elke bewering naar de bron met [1], [2], enzovoort.
    Noem bij een aanbeveling de klasse en het bewijsniveau.
    Beantwoorden de bronnen de vraag niet, zeg dan alleen: "Dit staat niet in de gevonden aanbevelingen."
    Antwoord in het Nederlands, in hoogstens vijf korte zinnen.
    """

    /// nil when available, otherwise why not, in Dutch.
    static var unavailableReason: String? {
        switch SystemLanguageModel.default.availability {
        case .available:
            return nil
        case .unavailable(.deviceNotEligible):
            return "Dit toestel ondersteunt Apple Intelligence niet."
        case .unavailable(.appleIntelligenceNotEnabled):
            return "Zet Apple Intelligence aan in Instellingen."
        case .unavailable(.modelNotReady):
            return "Het taalmodel wordt nog gedownload. Probeer het later opnieuw."
        case .unavailable:
            return "Apple Intelligence is niet beschikbaar."
        }
    }

    static func keywords(for question: String) async -> [String] {
        let session = LanguageModelSession(instructions: keywordInstructions)
        guard let response = try? await session.respond(to: question, options: GenerationOptions(temperature: 0)) else {
            return []
        }
        let terms = response.content
            .split(whereSeparator: { ",;\n".contains($0) })
            .map { $0.trimmingCharacters(in: CharacterSet(charactersIn: " -*•.0123456789)")) }
            .filter { !$0.isEmpty && $0.count <= 40 }
        return Array(terms.prefix(12))
    }

    static func prompt(question: String, hits: [AskSearch.Hit]) -> String {
        let sources = hits.prefix(sourcesForModel).enumerated().map { i, hit in
            let m = hit.chunk.metadata
            let guideline = [m.guideline ?? hit.project, m.year].compactMap { $0 }.joined(separator: " ")
            let grade = [m.recClass.map { "klasse " + $0.replacingOccurrences(of: "Class ", with: "") },
                         m.evidence.map { "niveau " + $0 }].compactMap { $0 }.joined(separator: ", ")
            var text = hit.chunk.text.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            if text.count > sourceChars { text = String(text.prefix(sourceChars)) + "…" }
            return "[\(i + 1)] \(guideline)\(grade.isEmpty ? "" : " (\(grade))"): \(text)"
        }
        return "Vraag: \(question)\n\nBronnen:\n" + sources.joined(separator: "\n")
    }

    /// Stream the answer; `update` gets the full text so far after each step.
    static func answer(question: String, hits: [AskSearch.Hit], update: @MainActor (String) -> Void) async throws {
        let session = LanguageModelSession(instructions: answerInstructions)
        let stream = session.streamResponse(
            to: prompt(question: question, hits: hits),
            options: GenerationOptions(temperature: 0.2)
        )
        for try await partial in stream {
            await update(partial.content)
        }
    }
}
