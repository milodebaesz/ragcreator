import SwiftUI

struct RecommendationDetailView: View {
    let recommendation: Recommendation

    @Environment(Library.self) private var library
    @State private var qa: [QAPair] = []
    /// 1-based page in the guideline PDF, when the desktop app indexed it.
    /// Looked up here, from the recommendation's own guideline: a page table
    /// handed down from the list could still belong to the previous one.
    @State private var page: Int?

    private var chunk: Chunk { recommendation.chunk }
    private var meta: ChunkMetadata { chunk.metadata }
    private var references: [ParsedReference] { meta.references.map(ParsedReference.init) }

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 10) {
                    GradeBadges(metadata: meta)
                    Text(chunk.text)
                        .font(.body)
                        .textSelection(.enabled)
                }
                .padding(.vertical, 4)
            }

            Section {
                NavigationLink {
                    PDFScreen(project: recommendation.project, page: page)
                } label: {
                    Label {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(page.map { "Open PDF op pagina \($0)" } ?? "Open PDF")
                            if page == nil {
                                Text("Pagina onbekend").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    } icon: {
                        Image(systemName: "doc.richtext")
                    }
                }
            }

            Section("Details") {
                detailRow("Richtlijn", [recommendation.project, meta.year].compactMap { $0 }.joined(separator: " · "))
                if let table = meta.tableTitle { detailRow("Tabel", table) }
                if let section = meta.section { detailRow("Sectie", section) }
                if let disease = meta.disease { detailRow("Aandoening", disease) }
                if let topic = meta.topic { detailRow("Onderwerp", topic.replacingOccurrences(of: "_", with: " ")) }
            }

            if !qa.isEmpty {
                Section("Q&A") {
                    ForEach(qa) { pair in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(pair.question).font(.subheadline.weight(.semibold))
                            Text(pair.answer).font(.subheadline).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }
            }

            Section {
                if references.isEmpty {
                    Text("Geen referenties bij deze aanbeveling.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(references, id: \.self) { ReferenceRow(reference: $0) }
                }
            } header: {
                Text("Referenties (\(references.count))")
            }
        }
        .navigationTitle(meta.recClass.map { "Aanbeveling · \($0.replacingOccurrences(of: "Class ", with: "klasse "))" } ?? "Aanbeveling")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            page = await library.pages(for: recommendation.project)[chunk.id]
            // Only the Dutch and English questions; "scenario" pairs are long
            // case vignettes that read poorly in a detail list.
            qa = await library.qaPairs(for: recommendation.project)
                .filter { $0.belongs(to: chunk.id) && $0.lang != "scenario" }
        }
    }

    /// Short values sit beside their label; long ones (table titles, section
    /// headings) underneath it, where they can wrap like a sentence.
    @ViewBuilder
    private func detailRow(_ label: String, _ value: String) -> some View {
        if value.count <= 28 {
            LabeledContent(label, value: value)
        } else {
            VStack(alignment: .leading, spacing: 3) {
                Text(label).font(.subheadline).foregroundStyle(.secondary)
                Text(value)
            }
            .padding(.vertical, 2)
        }
    }
}

struct ReferenceRow: View {
    let reference: ParsedReference
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if reference.number > 0 {
                    Text("\(reference.number)")
                        .font(.caption.weight(.semibold))
                        .monospacedDigit()
                        .foregroundStyle(Color.accent)
                }
                Text(reference.title ?? String(reference.raw.prefix(160)))
                    .font(.subheadline)
            }
            if !reference.shortCitation.isEmpty {
                Text(reference.shortCitation)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                linkButton("PubMed", reference.pubmedURL)
                if let doi = reference.doiURL { linkButton("Volledige tekst", doi) }
                linkButton("Scholar", reference.scholarURL)
            }
        }
        .padding(.vertical, 2)
    }

    private func linkButton(_ title: String, _ url: URL) -> some View {
        Button(title) { openURL(url) }
            .buttonStyle(.bordered)
            .controlSize(.small)
    }
}
