import SwiftUI

/// Asking the guidelines a question.
///
/// Searches recommendations and Q&A pairs only (AskSearch); Apple
/// Intelligence then writes a short answer from the best of those, citing them
/// by number, word by word as it is generated. Without Apple Intelligence the
/// screen still works as a search across all guidelines.
struct AskView: View {
    @Environment(Library.self) private var library

    enum Scope: Hashable { case all, current }
    enum Phase { case idle, keywords, searching, answering, done }

    @State private var question = ""
    @State private var scope: Scope = .all
    @State private var phase: Phase = .idle
    @State private var asked = ""
    @State private var keywords: [String] = []
    @State private var hits: [AskSearch.Hit] = []
    @State private var answer = ""
    @State private var aiError: String?
    @State private var task: Task<Void, Never>?
    @FocusState private var editing: Bool

    private let aiUnavailable = AppleAI.unavailableReason

    private static let examples = [
        "Wanneer is een statine geïndiceerd bij hartfalen?",
        "Welke antistolling bij longembolie en kanker?",
        "Mag iemand autorijden na een syncope?",
    ]

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                List {
                    questionSection
                    if phase == .idle {
                        introSection
                    } else {
                        if aiUnavailable == nil { answerSection(proxy) }
                        sourcesSection
                    }
                }
                .listStyle(.insetGrouped)
                .scrollDismissesKeyboard(.interactively)
            }
            .navigationTitle("Vraag")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: Recommendation.self) { RecommendationDetailView(recommendation: $0) }
        }
    }

    // MARK: - Sections

    private var questionSection: some View {
        Section {
            TextField("Stel een vraag over de aanbevelingen…", text: $question, axis: .vertical)
                .lineLimit(2...5)
                .focused($editing)
                .submitLabel(.search)
                .onSubmit { ask() }
            Picker("Zoeken in", selection: $scope) {
                Text("Alle richtlijnen").tag(Scope.all)
                Text(library.project ?? "Deze richtlijn").tag(Scope.current)
            }
            .pickerStyle(.segmented)
            Button {
                ask()
            } label: {
                Label(isBusy ? "Bezig…" : "Vraag", systemImage: "sparkles")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(isBusy || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        } footer: {
            if let aiUnavailable {
                Text("\(aiUnavailable) Je krijgt wel de best passende aanbevelingen, zonder samenvattend antwoord.")
            }
        }
    }

    private var introSection: some View {
        Section {
            ForEach(Self.examples, id: \.self) { example in
                Button(example) {
                    question = example
                    ask()
                }
            }
        } header: {
            Text("Probeer bijvoorbeeld")
        } footer: {
            Text(aiUnavailable == nil
                 ? "Zoekt in de aanbevelingen en Q&A-paren van je richtlijnen. Apple Intelligence vat de beste bronnen samen, op dit toestel, zonder internet."
                 : "Zoekt in de aanbevelingen en Q&A-paren van je richtlijnen.")
        }
    }

    private func answerSection(_ proxy: ScrollViewProxy) -> some View {
        Section {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Label("Apple Intelligence", systemImage: "sparkles")
                        .font(.caption.weight(.bold))
                        .textCase(.uppercase)
                        .foregroundStyle(Color.accent)
                    if let status = statusText {
                        ProgressView().controlSize(.small)
                        Text(status).font(.caption).foregroundStyle(.secondary)
                    }
                }
                if !answer.isEmpty {
                    Text(Self.attributed(answer, sources: min(hits.count, AppleAI.sourcesForModel)))
                        .textSelection(.enabled)
                        .environment(\.openURL, OpenURLAction { url in
                            if url.scheme == "source", let n = Int(url.host() ?? "") {
                                withAnimation { proxy.scrollTo("source-\(n)", anchor: .top) }
                            }
                            return .handled
                        })
                } else if let aiError {
                    Text(aiError).foregroundStyle(.red).font(.subheadline)
                } else if phase == .done && hits.isEmpty {
                    Text("Geen aanbevelingen gevonden.").foregroundStyle(.secondary)
                }
                if phase == .done && !answer.isEmpty {
                    Text("Samengevat uit de aanbevelingen hieronder; controleer altijd de bron voordat je ernaar handelt.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if !keywords.isEmpty {
                    Text("Gezocht op: \(keywords.joined(separator: ", "))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 4)
        }
    }

    @ViewBuilder
    private var sourcesSection: some View {
        if !hits.isEmpty {
            Section("Bronnen (\(hits.count))") {
                ForEach(Array(hits.enumerated()), id: \.element.id) { i, hit in
                    NavigationLink(value: hit.recommendation) {
                        SourceRow(number: i + 1, hit: hit,
                                  inAnswer: aiUnavailable != nil || i < AppleAI.sourcesForModel)
                    }
                    .id("source-\(i + 1)")
                }
            }
        } else if phase == .done {
            Section {
                Text("Geen aanbevelingen gevonden voor \"\(asked)\". Probeer andere woorden.")
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Asking

    private var isBusy: Bool { [.keywords, .searching, .answering].contains(phase) }

    private var statusText: String? {
        switch phase {
        case .keywords: "zoektermen bepalen…"
        case .searching: "zoeken…"
        case .answering where answer.isEmpty: "antwoord schrijven…"
        default: nil
        }
    }

    private func ask() {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty, !isBusy else { return }
        editing = false
        task?.cancel()
        asked = q
        keywords = []
        hits = []
        answer = ""
        aiError = nil

        task = Task {
            let useAI = aiUnavailable == nil
            if useAI {
                phase = .keywords
                keywords = await AppleAI.keywords(for: q)
            }
            guard !Task.isCancelled else { return }

            phase = .searching
            let projects = scope == .all ? library.projects : [library.project].compactMap { $0 }
            let corpora = await library.corpora(for: projects)
            let query = ([q] + keywords).joined(separator: " ")
            hits = await Task.detached { AskSearch.rank(corpora, query: query) }.value
            guard !Task.isCancelled else { return }

            if useAI && !hits.isEmpty {
                phase = .answering
                do {
                    try await AppleAI.answer(question: q, hits: hits) { text in answer = text }
                } catch {
                    aiError = error.localizedDescription
                }
            }
            phase = .done
        }
    }

    /// The answer with **bold** kept and each real [n] citation turned into a
    /// tappable link to its source. A number beyond the sources the model got
    /// stays plain text — the model made it up.
    static func attributed(_ text: String, sources: Int) -> AttributedString {
        var result = (try? AttributedString(
            markdown: text,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(text)

        let plain = String(result.characters)
        guard let re = try? NSRegularExpression(pattern: #"\[(\d+)\]"#) else { return result }
        for match in re.matches(in: plain, range: NSRange(plain.startIndex..., in: plain)).reversed() {
            guard let r = Range(match.range, in: plain),
                  let numRange = Range(match.range(at: 1), in: plain),
                  let n = Int(plain[numRange]), (1...max(sources, 1)).contains(n), sources > 0,
                  let lower = AttributedString.Index(r.lowerBound, within: result),
                  let upper = AttributedString.Index(r.upperBound, within: result) else { continue }
            result[lower..<upper].link = URL(string: "source://\(n)")
            result[lower..<upper].foregroundColor = Color.accent
            result[lower..<upper].font = .body.weight(.semibold)
        }
        return result
    }
}

private struct SourceRow: View {
    let number: Int
    let hit: AskSearch.Hit
    let inAnswer: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Text("\(number)")
                    .font(.caption.weight(.bold))
                    .monospacedDigit()
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .foregroundStyle(Color.accent)
                    .background(Color.accent.opacity(0.16), in: RoundedRectangle(cornerRadius: 5))
                Text([hit.project, hit.chunk.metadata.year].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                GradeBadges(metadata: hit.chunk.metadata)
            }
            if let qa = hit.qa {
                Text("Q&A: \(qa.question)")
                    .font(.caption)
                    .italic()
                    .foregroundStyle(.secondary)
            }
            Text(hit.chunk.text)
                .font(.subheadline)
                .lineLimit(5)
            if !inAnswer {
                Text("niet gebruikt in het antwoord")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 2)
    }
}
