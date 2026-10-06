import SwiftUI

/// Every recommendation of the current guideline, grouped by recommendation
/// table in the guideline's own order, with search and filters.
struct RecommendationsView: View {
    @Environment(Library.self) private var library

    @State private var chunks: [Chunk] = []
    @State private var loadError: String?
    @State private var query = ""
    @State private var classFilter: String?
    @State private var diseaseFilter: String?
    @State private var topicFilter: String?

    private static let classes = ["Class I", "Class IIa", "Class IIb", "Class III"]

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(library.project ?? "Aanbevelingen")
                .navigationBarTitleDisplayMode(.inline)
                .searchable(text: $query, prompt: "Zoek in aanbevelingen")
                .projectTitleMenu()
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) { filterMenu }
                }
                .navigationDestination(for: Recommendation.self) { rec in
                    RecommendationDetailView(recommendation: rec)
                }
                .task(id: library.project) { await load() }
                .refreshable { await library.refresh() }
        }
    }

    @ViewBuilder
    private var content: some View {
        if let loadError {
            ContentUnavailableView("Kon de aanbevelingen niet laden", systemImage: "exclamationmark.triangle", description: Text(loadError))
        } else if filtered.isEmpty && !chunks.isEmpty {
            ContentUnavailableView.search(text: query)
        } else {
            List {
                if isFiltering {
                    Section {
                        ForEach(filtered, id: \.id) { row($0) }
                    } header: {
                        Text("\(filtered.count) \(filtered.count == 1 ? "treffer" : "treffers")")
                    }
                } else {
                    ForEach(groups, id: \.title) { group in
                        Section(group.title) {
                            ForEach(group.chunks, id: \.id) { row($0) }
                        }
                    }
                }
            }
            .listStyle(.insetGrouped)
        }
    }

    private func row(_ chunk: Chunk) -> some View {
        NavigationLink(value: Recommendation(project: library.project ?? "", chunk: chunk)) {
            VStack(alignment: .leading, spacing: 6) {
                GradeBadges(metadata: chunk.metadata)
                Text(chunk.text)
                    .font(.subheadline)
                    .lineLimit(5)
            }
            .padding(.vertical, 2)
        }
    }

    private var filterMenu: some View {
        Menu {
            Picker("Klasse", selection: $classFilter) {
                Text("Alle klassen").tag(String?.none)
                ForEach(Self.classes, id: \.self) { Text($0).tag(Optional($0)) }
            }
            .pickerStyle(.menu)
            Picker("Aandoening", selection: $diseaseFilter) {
                Text("Alle aandoeningen").tag(String?.none)
                ForEach(values(\.disease), id: \.self) { Text($0).tag(Optional($0)) }
            }
            .pickerStyle(.menu)
            Picker("Onderwerp", selection: $topicFilter) {
                Text("Alle onderwerpen").tag(String?.none)
                ForEach(values(\.topic), id: \.self) { Text($0.replacingOccurrences(of: "_", with: " ")).tag(Optional($0)) }
            }
            .pickerStyle(.menu)
            if activeFilters > 0 {
                Button("Filters wissen", systemImage: "xmark.circle", role: .destructive) {
                    classFilter = nil
                    diseaseFilter = nil
                    topicFilter = nil
                }
            }
        } label: {
            Label("Filters", systemImage: activeFilters > 0
                  ? "line.3.horizontal.decrease.circle.fill"
                  : "line.3.horizontal.decrease.circle")
        }
    }

    // MARK: - Data

    private func load() async {
        guard let project = library.project else { return }
        loadError = nil
        do {
            chunks = try await library.chunks(for: project)
        } catch {
            chunks = []
            loadError = error.localizedDescription
        }
    }

    private var activeFilters: Int {
        [classFilter, diseaseFilter, topicFilter].compactMap { $0 }.count
    }

    private var isFiltering: Bool {
        activeFilters > 0 || !query.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func values(_ key: KeyPath<ChunkMetadata, String?>) -> [String] {
        Array(Set(chunks.compactMap { $0.metadata[keyPath: key] })).sorted()
    }

    private var filtered: [Chunk] {
        let q = query.trimmingCharacters(in: .whitespaces)
        return chunks.filter { c in
            let m = c.metadata
            if let classFilter, m.recClass != classFilter { return false }
            if let diseaseFilter, m.disease != diseaseFilter { return false }
            if let topicFilter, m.topic != topicFilter { return false }
            guard !q.isEmpty else { return true }
            return [c.text, m.section ?? "", m.tableTitle ?? ""].contains {
                $0.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]) != nil
            }
        }
    }

    private struct Group {
        let title: String
        let chunks: [Chunk]
    }

    /// Recommendation tables in the guideline's numbering, not alphabetically.
    private var groups: [Group] {
        var order: [String] = []
        var byTable: [String: [Chunk]] = [:]
        for c in chunks {
            let title = c.metadata.tableTitle?.trimmingCharacters(in: .whitespaces).nilIfEmpty ?? "Overig"
            if byTable[title] == nil { order.append(title) }
            byTable[title, default: []].append(c)
        }
        order.sort { a, b in
            switch (Self.tableNumber(a), Self.tableNumber(b)) {
            case let (x?, y?): x < y
            case (_?, nil): true
            case (nil, _?): false
            default: false
            }
        }
        return order.map { Group(title: Self.shortTitle($0), chunks: byTable[$0] ?? []) }
    }

    static func tableNumber(_ title: String) -> Int? {
        guard let r = title.range(of: #"(?i)table\s+(\d+)"#, options: .regularExpression) else { return nil }
        return Int(title[r].filter(\.isNumber))
    }

    /// "Recommendation Table 7 — Recommendations for …" reads as a header
    /// without the repeated "Recommendations for".
    static func shortTitle(_ title: String) -> String {
        title.replacingOccurrences(of: "Recommendation Table", with: "Tabel")
    }
}
