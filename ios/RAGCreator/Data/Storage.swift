import Foundation

/// Where the data lives and how to read it.
///
/// The desktop app writes into the app's iCloud container (see
/// src-tauri/src/storage.rs); this side only reads. Without iCloud the app
/// falls back to its own Documents folder, which the Files app exposes, so
/// project folders can be copied in by hand.
enum Storage {
    static let containerID = "iCloud.com.ragcreator.app"
    static let medDir = "medical_rag_project"

    struct Root {
        let url: URL
        let usesICloud: Bool

        var medRoot: URL { url.appendingPathComponent(Storage.medDir, isDirectory: true) }
        var projectsDir: URL { medRoot.appendingPathComponent("projects", isDirectory: true) }

        func projectDir(_ project: String) -> URL {
            projectsDir.appendingPathComponent(project, isDirectory: true)
        }
    }

    /// Resolve the root. Apple documents the container lookup as slow enough
    /// that it must stay off the main thread.
    static func resolveRoot() async -> Root {
        await Task.detached(priority: .userInitiated) {
            let fm = FileManager.default
            if let container = fm.url(forUbiquityContainerIdentifier: containerID) {
                let docs = container.appendingPathComponent("Documents", isDirectory: true)
                return Root(url: docs, usesICloud: true)
            }
            let docs = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
            return Root(url: docs, usesICloud: false)
        }.value
    }

    /// `.name.icloud`: what iCloud leaves in place of a file it has not
    /// downloaded yet.
    static func placeholder(for url: URL) -> URL {
        url.deletingLastPathComponent().appendingPathComponent("." + url.lastPathComponent + ".icloud")
    }

    /// The file a placeholder stands for, or nil for an ordinary name.
    static func realName(ofPlaceholder name: String) -> String? {
        guard name.hasPrefix("."), name.hasSuffix(".icloud"), name.count > ".icloud".count + 1 else {
            return nil
        }
        return String(name.dropFirst().dropLast(".icloud".count))
    }

    /// Whether the file exists here or in iCloud.
    static func exists(_ url: URL) -> Bool {
        let fm = FileManager.default
        return fm.fileExists(atPath: url.path) || fm.fileExists(atPath: placeholder(for: url).path)
    }

    /// Read a file, letting iCloud download it first when needed.
    ///
    /// A coordinated read is what makes iCloud fetch an undownloaded file
    /// before handing it over; a plain read would just fail.
    static func read(_ url: URL) throws -> Data {
        var result: Result<Data, Error> = .failure(CocoaError(.fileReadNoSuchFile))
        var coordinationError: NSError?
        NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { readURL in
            result = Result { try Data(contentsOf: readURL) }
        }
        if let coordinationError { throw coordinationError }
        return try result.get()
    }

    /// Make sure a large file (a PDF) is on disk, then return its URL.
    static func download(_ url: URL) throws -> URL {
        var coordinationError: NSError?
        var available = false
        NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { readURL in
            available = FileManager.default.fileExists(atPath: readURL.path)
        }
        if let coordinationError { throw coordinationError }
        guard available else { throw CocoaError(.fileReadNoSuchFile) }
        return url
    }

    static func decode<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        try JSONDecoder().decode(type, from: read(url))
    }

    /// Folder names in `dir`, for projects copied in without a config.
    static func subdirectories(of dir: URL) -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        return names.filter { name in
            var isDir: ObjCBool = false
            return !name.hasPrefix(".")
                && FileManager.default.fileExists(atPath: dir.appendingPathComponent(name).path, isDirectory: &isDir)
                && isDir.boolValue
        }.sorted()
    }

    /// The first PDF in a project folder, downloaded or not.
    static func pdf(in dir: URL) -> URL? {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        let pdfs = names
            .map { realName(ofPlaceholder: $0) ?? $0 }
            .filter { $0.lowercased().hasSuffix(".pdf") && !$0.hasPrefix(".") }
            .sorted()
        return pdfs.first.map { dir.appendingPathComponent($0) }
    }
}
