import PDFKit
import SwiftUI

/// The guideline PDF in Apple's own viewer: pinch-zoom, text selection and
/// smooth scrolling come with PDFKit, and it only renders what is on screen.
struct PDFScreen: View {
    let project: String
    /// 1-based page to open on.
    var page: Int?
    /// In the Richtlijn tab the title doubles as the guideline picker, so it
    /// names the guideline; pushed from a recommendation it shows the page.
    var showsProjectInTitle = false

    @Environment(Library.self) private var library
    @State private var document: PDFDocument?
    @State private var error: String?
    @State private var currentPage = 1

    var body: some View {
        Group {
            if let document {
                PDFKitView(document: document, startPage: page, currentPage: $currentPage)
                    .ignoresSafeArea(edges: .bottom)
            } else if let error {
                ContentUnavailableView("PDF niet beschikbaar", systemImage: "doc.questionmark", description: Text(error))
            } else {
                ProgressView("PDF laden…")
            }
        }
        .navigationTitle(showsProjectInTitle || document == nil ? project : pageTitle)
        .toolbar {
            if showsProjectInTitle, let document {
                ToolbarItem(placement: .topBarTrailing) {
                    Text("\(currentPage) / \(document.pageCount)")
                        .font(.subheadline.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: project) { await load() }
    }

    /// "Pagina 12 van 61", plus the number printed on the page when the PDF
    /// numbers its pages differently (a journal reprint starting at 543).
    private var pageTitle: String {
        guard let document else { return project }
        var title = "Pagina \(currentPage) van \(document.pageCount)"
        if let label = document.page(at: currentPage - 1)?.label, !label.isEmpty, label != "\(currentPage)" {
            title += " · p. \(label)"
        }
        return title
    }

    private func load() async {
        document = nil
        error = nil
        do {
            let url = try await library.pdfURL(for: project)
            let doc = await Task.detached { PDFDocument(url: url) }.value
            guard let doc else { throw CocoaError(.fileReadCorruptFile) }
            document = doc
        } catch {
            self.error = "Geen PDF gevonden voor \(project). Koppel een PDF in de desktop-app en voer stap 1 uit."
        }
    }
}

struct PDFKitView: UIViewRepresentable {
    let document: PDFDocument
    let startPage: Int?
    @Binding var currentPage: Int

    func makeUIView(context: Context) -> PDFView {
        let view = JumpingPDFView()
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.autoScales = true
        view.pageShadowsEnabled = true
        view.document = document
        if let startPage {
            view.pendingPage = document.page(at: max(0, min(startPage, document.pageCount) - 1))
        }
        context.coordinator.observe(view)
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document !== document { view.document = document }
    }

    func makeCoordinator() -> Coordinator { Coordinator(currentPage: $currentPage) }

    final class Coordinator: NSObject {
        let currentPage: Binding<Int>
        private var token: NSObjectProtocol?

        init(currentPage: Binding<Int>) { self.currentPage = currentPage }

        func observe(_ view: PDFView) {
            token = NotificationCenter.default.addObserver(
                forName: .PDFViewPageChanged, object: view, queue: .main
            ) { [weak self, weak view] _ in
                guard let view, let page = view.currentPage, let doc = view.document else { return }
                self?.currentPage.wrappedValue = doc.index(for: page) + 1
            }
        }

        deinit {
            if let token { NotificationCenter.default.removeObserver(token) }
        }
    }
}

/// A PDFView that opens on a given page.
///
/// A jump made right after creation gets lost: the view has no final size
/// yet (it is still sliding in), and when autoScales fits the page to the
/// width on the first real layout, PDFKit scrolls back to the top. So the
/// jump waits for a layout with a real size, and is repeated until the page
/// actually is the current one.
final class JumpingPDFView: PDFView {
    var pendingPage: PDFPage?
    private var attempts = 0

    override func layoutSubviews() {
        super.layoutSubviews()
        guard let target = pendingPage, bounds.width > 0, bounds.height > 0, document != nil else { return }
        attempts += 1
        if currentPage == target || attempts > 6 {
            pendingPage = nil
            return
        }
        // A destination at the page's top edge, not just the page: go(to: page)
        // leaves the end of the previous page in view.
        let top = target.bounds(for: displayBox).maxY
        go(to: PDFDestination(page: target, at: CGPoint(x: 0, y: top)))
        // The layout pass that follows a jump does not always come by itself.
        DispatchQueue.main.async { [weak self] in self?.setNeedsLayout() }
    }
}

/// The Richtlijn tab: the current guideline's PDF, remembering the page.
struct GuidelinePDFTab: View {
    @Environment(Library.self) private var library

    var body: some View {
        NavigationStack {
            if let project = library.project {
                PDFScreen(project: project, page: nil, showsProjectInTitle: true)
                    .id(project)
                    .projectTitleMenu()
            } else {
                ContentUnavailableView("Geen richtlijn gekozen", systemImage: "doc.text")
            }
        }
    }
}
