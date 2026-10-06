import SwiftUI

@main
struct RAGCreatorApp: App {
    @State private var library = Library()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(library)
                .tint(.accent)
                .task { await library.load() }
        }
    }
}

extension Color {
    /// The amber of the desktop app, so a recommendation looks the same on both.
    static let accent = Color(red: 0.79, green: 0.56, blue: 0.25)
}
