import SwiftUI

struct RootView: View {
    @Environment(Library.self) private var library

    enum Tab: Hashable { case ask, recommendations, guideline, qa, overview }

    @SceneStorage("tab") private var tab: Tab = .recommendations

    var body: some View {
        switch library.state {
        case .loading:
            ProgressView("Richtlijnen laden…")
        case .empty:
            EmptyLibraryView()
        case .failed(let message):
            ContentUnavailableView("Kon de richtlijnen niet laden", systemImage: "exclamationmark.triangle", description: Text(message))
        case .ready:
            TabView(selection: $tab) {
                SwiftUI.Tab("Vraag", systemImage: "sparkles", value: Tab.ask) {
                    ComingSoonView(title: "Vraag", systemImage: "sparkles",
                                   text: "Vragen stellen met Apple Intelligence komt in de volgende stap. Gebruik tot die tijd de huidige RAGCreator-app.")
                }
                SwiftUI.Tab("Aanbevelingen", systemImage: "checklist", value: Tab.recommendations) {
                    RecommendationsView()
                }
                SwiftUI.Tab("Richtlijn", systemImage: "doc.text", value: Tab.guideline) {
                    GuidelinePDFTab()
                }
                SwiftUI.Tab("Q&A", systemImage: "bubble.left.and.bubble.right", value: Tab.qa) {
                    ComingSoonView(title: "Q&A", systemImage: "bubble.left.and.bubble.right",
                                   text: "De Q&A-paren komen in een volgende stap.")
                }
                SwiftUI.Tab("Overzicht", systemImage: "chart.bar", value: Tab.overview) {
                    ComingSoonView(title: "Overzicht", systemImage: "chart.bar",
                                   text: "Het overzicht met grafieken komt in een volgende stap.")
                }
            }
        }
    }
}

extension RootView.Tab: RawRepresentable {
    init?(rawValue: String) {
        switch rawValue {
        case "ask": self = .ask
        case "guideline": self = .guideline
        case "qa": self = .qa
        case "overview": self = .overview
        default: self = .recommendations
        }
    }

    var rawValue: String {
        switch self {
        case .ask: "ask"
        case .recommendations: "recommendations"
        case .guideline: "guideline"
        case .qa: "qa"
        case .overview: "overview"
        }
    }
}

/// The guideline picker, as the menu under every tab's navigation title:
/// tapping "ESC Hartfalen ⌄" is how iOS apps switch what a screen shows.
struct ProjectMenuItems: View {
    @Environment(Library.self) private var library

    var body: some View {
        @Bindable var library = library
        Picker("Richtlijn", selection: $library.project) {
            ForEach(library.projects, id: \.self) { name in
                if let year = library.year(of: name) {
                    Text(name).badge(year).tag(Optional(name))
                } else {
                    Text(name).tag(Optional(name))
                }
            }
        }
        Divider()
        Button("Opnieuw laden", systemImage: "arrow.clockwise") {
            Task { await library.refresh() }
        }
    }
}

extension View {
    func projectTitleMenu() -> some View {
        toolbarTitleMenu { ProjectMenuItems() }
    }
}

struct ComingSoonView: View {
    let title: String
    let systemImage: String
    let text: String

    var body: some View {
        NavigationStack {
            ContentUnavailableView(title, systemImage: systemImage, description: Text(text))
                .navigationTitle(title)
        }
    }
}

struct EmptyLibraryView: View {
    @Environment(Library.self) private var library

    var body: some View {
        ContentUnavailableView {
            Label("Nog geen richtlijn", systemImage: "books.vertical")
        } description: {
            if library.usesICloud {
                Text("Open RAGCreator op je Mac: die zet de richtlijnen in de iCloud-map van RAGCreator. Zodra iCloud klaar is verschijnen ze hier.")
            } else {
                Text("iCloud Drive is niet beschikbaar. Zet iCloud Drive aan, of zet de projectmappen in de map van deze app in de Bestanden-app.")
            }
        } actions: {
            Button("Opnieuw proberen") { Task { await library.refresh() } }
        }
    }
}
