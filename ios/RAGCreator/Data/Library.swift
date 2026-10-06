import Foundation
import Observation

/// Everything the app shows, loaded from the iCloud container on demand.
///
/// One instance for the whole app, shared through the environment. Files are
/// read off the main thread and cached per guideline; the desktop app only
/// rewrites them between sessions, so a reload on project switch is enough.
@MainActor
@Observable
final class Library {
    enum State: Equatable {
        case loading
        case ready
        case empty
        case failed(String)
    }

    private(set) var state: State = .loading
    private(set) var root: Storage.Root?
    private(set) var projects: [String] = []
    private(set) var meta: [String: ProjectMeta] = [:]

    /// The guideline picked in the toolbar, shared by every tab.
    var project: String? {
        didSet { UserDefaults.standard.set(project, forKey: "project") }
    }

    private var chunkCache: [String: [Chunk]] = [:]
    private var pageCache: [String: [String: Int]] = [:]
    private var qaCache: [String: [QAPair]] = [:]

    var usesICloud: Bool { root?.usesICloud ?? false }

    func year(of project: String) -> String? { meta[project]?.year }

    func load() async {
        state = .loading
        let root = await Storage.resolveRoot()
        self.root = root

        let loaded: (Config?, [String]) = await Task.detached {
            let config = try? Storage.decode(Config.self, from: root.medRoot.appendingPathComponent("rag_config.json"))
            return (config, Storage.subdirectories(of: root.projectsDir))
        }.value

        let (config, folders) = loaded
        meta = config?.projectMeta ?? [:]
        // Listed in the config first, in its order; folders copied in by hand
        // after that.
        // A listed project without a folder is skipped — unless there are no
        // folders at all yet, which is iCloud still creating them.
        var names = config?.projects ?? []
        if !folders.isEmpty { names = names.filter(folders.contains) }
        names += folders.filter { !names.contains($0) }
        projects = names

        let remembered = UserDefaults.standard.string(forKey: "project")
        if let remembered, names.contains(remembered) {
            project = remembered
        } else if let active = config?.active, names.contains(active) {
            project = active
        } else {
            project = names.first
        }
        state = names.isEmpty ? .empty : .ready
    }

    /// Drop cached files so the next read sees what the desktop wrote since.
    func refresh() async {
        chunkCache = [:]
        pageCache = [:]
        qaCache = [:]
        await load()
    }

    func chunks(for project: String) async throws -> [Chunk] {
        if let cached = chunkCache[project] { return cached }
        guard let root else { return [] }
        let url = root.projectDir(project).appendingPathComponent("rag_chunks.json")
        let chunks: [Chunk] = try await Task.detached {
            guard Storage.exists(url) else { return [] }
            return try Storage.decode([Chunk].self, from: url)
        }.value
        chunkCache[project] = chunks
        return chunks
    }

    /// chunk id → 1-based PDF page, from the index the desktop app builds.
    func pages(for project: String) async -> [String: Int] {
        if let cached = pageCache[project] { return cached }
        guard let root else { return [:] }
        let url = root.projectDir(project).appendingPathComponent("pdf_pages.json")
        let zeroBased: [String: Int] = await Task.detached {
            (try? Storage.decode([String: Int].self, from: url)) ?? [:]
        }.value
        let pages = zeroBased.mapValues { $0 + 1 }
        pageCache[project] = pages
        return pages
    }

    func qaPairs(for project: String) async -> [QAPair] {
        if let cached = qaCache[project] { return cached }
        guard let root else { return [] }
        let url = root.projectDir(project).appendingPathComponent("qa_pairs.json")
        let pairs: [QAPair] = await Task.detached {
            guard Storage.exists(url) else { return [] }
            return (try? Storage.decode([QAPair].self, from: url)) ?? []
        }.value
        qaCache[project] = pairs
        return pairs
    }

    /// The guideline PDF on disk, downloading it from iCloud if needed.
    func pdfURL(for project: String) async throws -> URL {
        guard let root else { throw CocoaError(.fileReadNoSuchFile) }
        let dir = root.projectDir(project)
        return try await Task.detached {
            guard let url = Storage.pdf(in: dir) else { throw CocoaError(.fileReadNoSuchFile) }
            return try Storage.download(url)
        }.value
    }
}
