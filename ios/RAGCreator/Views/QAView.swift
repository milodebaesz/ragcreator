import SwiftUI

/// The generated question/answer pairs of the current guideline. Tapping one
/// opens the recommendation it was generated from.
struct QAView: View {
    @Environment(Library.self) private var library

    enum Language: String, CaseIterable, Identifiable {
        case nl, en, all
        var id: String { rawValue }
        var title: String {
            switch self {
            case .nl: "Nederlands"
            case .en: "Engels"
            case .all: "Alle"
            }
        }
    }

    @State private var pairs: [QAPair] = []
    @State private var chunks: [Chunk] = []
    @State private var query = ""
    @State private var language: Language = .nl
    @State private var loading = true

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(library.project ?? "Q&A")
                .navigationBarTitleDisplayMode(.inline)
                .projectTitleMenu()
                .searchable(text: $query, prompt: "Zoek in vragen en antwoorden")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Picker("Taal", selection: $language) {
                                ForEach(Language.allCases) { Text($0.title).tag($0) }
                            }
                        } label: {
                            Label("Taal", systemImage: "globe")
                        }
                    }
                }
                .navigationDestination(for: Recommendation.self) { RecommendationDetailView(recommendation: $0) }
                .task(id: library.project) { await load() }
        }
    }

    @ViewBuilder
    private var content: some View {
        if loading {
            ProgressView()
        } else if pairs.isEmpty {
            ContentUnavailableView("Nog geen Q&A-paren", systemImage: "bubble.left.and.bubble.right",
                                   description: Text("Draai stap 3 van de pijplijn op de Mac voor deze richtlijn."))
        } else if filtered.isEmpty {
            ContentUnavailableView.search(text: query)
        } else {
            List {
                Section {
                    ForEach(filtered) { pair in
                        if let chunk = chunks.first(where: { pair.belongs(to: $0.id) }) {
                            NavigationLink(value: Recommendation(project: library.project ?? "", chunk: chunk)) {
                                QARow(pair: pair)
                            }
                        } else {
                            QARow(pair: pair)
                        }
                    }
                } header: {
                    Text("\(filtered.count) \(filtered.count == 1 ? "vraag" : "vragen")")
                }
            }
            .listStyle(.insetGrouped)
        }
    }

    private var filtered: [QAPair] {
        let q = query.trimmingCharacters(in: .whitespaces)
        return pairs.filter { pair in
            switch language {
            case .nl: if pair.lang != "nl" { return false }
            case .en: if pair.lang != "en" { return false }
            case .all: break
            }
            guard !q.isEmpty else { return true }
            return [pair.question, pair.answer].contains {
                $0.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil
            }
        }
    }

    private func load() async {
        guard let project = library.project else { return }
        loading = true
        pairs = await library.qaPairs(for: project)
        chunks = (try? await library.chunks(for: project)) ?? []
        // Files without a language tag would vanish under the default filter.
        if !pairs.contains(where: { $0.lang == "nl" }) { language = .all }
        loading = false
    }
}

private struct QARow: View {
    let pair: QAPair

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(pair.question)
                .font(.subheadline.weight(.semibold))
            Text(pair.answer)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(4)
        }
        .padding(.vertical, 2)
    }
}
