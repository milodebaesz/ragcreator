import SwiftUI

/// Class of recommendation and level of evidence, coloured the way the ESC
/// tables colour them: green for I / A, amber for IIa–IIb / B, red for III.
struct GradeBadges: View {
    let metadata: ChunkMetadata

    var body: some View {
        HStack(spacing: 6) {
            if let cls = metadata.recClass {
                Badge(text: cls.replacingOccurrences(of: "Class ", with: ""), color: Self.classColor(cls))
            }
            if let ev = metadata.evidence {
                Badge(text: ev, color: Self.evidenceColor(ev))
            }
            if metadata.approved {
                Image(systemName: "checkmark.seal.fill")
                    .font(.caption)
                    .foregroundStyle(.green)
                    .accessibilityLabel("Geaccordeerd")
            }
        }
    }

    static func classColor(_ cls: String) -> Color {
        if cls.contains("IIa") { return .orange }
        if cls.contains("IIb") { return .yellow }
        if cls.contains("III") { return .red }
        if cls.contains("I") { return .green }
        return .gray
    }

    static func evidenceColor(_ ev: String) -> Color {
        switch ev {
        case "A": .green
        case "B", "B1", "B2": .orange
        default: .gray
        }
    }
}

struct Badge: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.bold))
            .monospacedDigit()
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.16), in: RoundedRectangle(cornerRadius: 5))
    }
}
