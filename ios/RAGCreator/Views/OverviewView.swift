import Charts
import SwiftUI

/// What a guideline holds: counts, the class and evidence distribution, and
/// its recommendation tables.
struct OverviewView: View {
    @Environment(Library.self) private var library
    @State private var chunks: [Chunk] = []
    @State private var qaCount = 0

    private static let classOrder = ["Class I", "Class IIa", "Class IIb", "Class III"]
    private static let evidenceOrder = ["A", "B1", "B2", "B", "C", "NR"]

    var body: some View {
        NavigationStack {
            List {
                Section {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                        StatTile(value: chunks.count, label: "Aanbevelingen", systemImage: "checklist")
                        StatTile(value: tables.count, label: "Tabellen", systemImage: "tablecells")
                        StatTile(value: chunks.filter { $0.metadata.evidence == "A" }.count, label: "Bewijsniveau A", systemImage: "star")
                        StatTile(value: qaCount, label: "Q&A-paren", systemImage: "bubble.left.and.bubble.right")
                    }
                    .padding(.vertical, 4)
                    if !chunks.isEmpty {
                        let approved = chunks.filter(\.metadata.approved).count
                        LabeledContent("Geaccordeerd", value: "\(approved) van \(chunks.count)")
                        ProgressView(value: Double(approved), total: Double(max(chunks.count, 1)))
                            .tint(.green)
                    }
                }

                if !chunks.isEmpty {
                    Section("Klasse van aanbeveling") {
                        distributionChart(counts(\.recClass, order: Self.classOrder), color: { GradeBadges.classColor($0) })
                    }
                    Section("Bewijsniveau") {
                        distributionChart(counts(\.evidence, order: Self.evidenceOrder), color: { GradeBadges.evidenceColor($0) })
                    }
                    Section("Tabellen") {
                        ForEach(tables, id: \.title) { table in
                            HStack {
                                Text(table.title).font(.subheadline)
                                Spacer()
                                Text("\(table.count)")
                                    .font(.subheadline.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                if let root = library.root {
                    Section("Opslag") {
                        LabeledContent("Bron", value: root.usesICloud ? "iCloud Drive" : "Op dit toestel")
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle(library.project ?? "Overzicht")
            .navigationBarTitleDisplayMode(.inline)
            .projectTitleMenu()
            .task(id: library.project) { await load() }
        }
    }

    private func distributionChart(_ data: [(label: String, count: Int)], color: @escaping (String) -> Color) -> some View {
        Chart(data, id: \.label) { item in
            BarMark(x: .value("Aantal", item.count), y: .value("Label", shortLabel(item.label)))
                .foregroundStyle(color(item.label))
                .annotation(position: .trailing) {
                    Text("\(item.count)").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
        }
        .chartXAxis(.hidden)
        .frame(height: CGFloat(data.count) * 34 + 10)
        .padding(.vertical, 6)
    }

    private func shortLabel(_ label: String) -> String {
        label.replacingOccurrences(of: "Class ", with: "Klasse ")
    }

    private func counts(_ key: KeyPath<ChunkMetadata, String?>, order: [String]) -> [(label: String, count: Int)] {
        var counts: [String: Int] = [:]
        for c in chunks { counts[c.metadata[keyPath: key] ?? "Onbekend", default: 0] += 1 }
        let extra = counts.keys.filter { !order.contains($0) }.sorted()
        return (order + extra).compactMap { label in counts[label].map { (label, $0) } }
    }

    private var tables: [(title: String, count: Int)] {
        var order: [String] = []
        var counts: [String: Int] = [:]
        for c in chunks {
            guard let t = c.metadata.tableTitle?.trimmingCharacters(in: .whitespaces), !t.isEmpty else { continue }
            if counts[t] == nil { order.append(t) }
            counts[t, default: 0] += 1
        }
        order.sort { (RecommendationsView.tableNumber($0) ?? .max) < (RecommendationsView.tableNumber($1) ?? .max) }
        return order.map { (RecommendationsView.shortTitle($0), counts[$0] ?? 0) }
    }

    private func load() async {
        guard let project = library.project else { return }
        chunks = (try? await library.chunks(for: project)) ?? []
        qaCount = await library.qaPairs(for: project).filter { $0.lang != "scenario" }.count
    }
}

private struct StatTile: View {
    let value: Int
    let label: String
    let systemImage: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: systemImage)
                .font(.subheadline)
                .foregroundStyle(Color.accent)
            Text("\(value)")
                .font(.title2.weight(.semibold).monospacedDigit())
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color(.tertiarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
    }
}
