import Foundation

// The files the desktop app writes into the iCloud container. Every field the
// pipeline may leave out is optional, so one older file never stops a whole
// guideline from loading.

struct Config: Decodable {
    var active: String
    var projects: [String]
    var projectMeta: [String: ProjectMeta]

    enum CodingKeys: String, CodingKey {
        case active, projects
        case projectMeta = "project_meta"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        active = try c.decodeIfPresent(String.self, forKey: .active) ?? ""
        projects = try c.decodeIfPresent([String].self, forKey: .projects) ?? []
        projectMeta = try c.decodeIfPresent([String: ProjectMeta].self, forKey: .projectMeta) ?? [:]
    }
}

struct ProjectMeta: Decodable {
    var year: String?
    var pdfName: String?

    enum CodingKeys: String, CodingKey {
        case year
        case pdfName = "pdf_name"
    }
}

struct ReferenceEntry: Decodable, Hashable {
    var id: Int
    var text: String

    /// Older chunk files stored references as plain strings.
    init(from decoder: Decoder) throws {
        if let text = try? decoder.singleValueContainer().decode(String.self) {
            self.id = 0
            self.text = text
            return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(Int.self, forKey: .id) ?? 0
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
    }

    enum CodingKeys: String, CodingKey { case id, text }
}

struct ChunkMetadata: Decodable, Hashable {
    var type: String?
    var recClass: String?
    var evidence: String?
    var disease: String?
    var topic: String?
    var section: String?
    var tableTitle: String?
    var guideline: String?
    var year: String?
    var references: [ReferenceEntry]
    var refIds: [Int]
    var approved: Bool

    enum CodingKeys: String, CodingKey {
        case type, evidence, disease, topic, section, guideline, year, references, approved
        case recClass = "class"
        case tableTitle = "table_title"
        case refIds = "ref_ids"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decodeIfPresent(String.self, forKey: .type)
        recClass = try c.decodeIfPresent(String.self, forKey: .recClass)
        evidence = try c.decodeIfPresent(String.self, forKey: .evidence)
        disease = try c.decodeIfPresent(String.self, forKey: .disease)
        topic = try c.decodeIfPresent(String.self, forKey: .topic)
        section = try c.decodeIfPresent(String.self, forKey: .section)
        tableTitle = try c.decodeIfPresent(String.self, forKey: .tableTitle)
        guideline = try c.decodeIfPresent(String.self, forKey: .guideline)
        year = try c.decodeIfPresent(String.self, forKey: .year)
        references = (try? c.decodeIfPresent([ReferenceEntry].self, forKey: .references)) ?? []
        refIds = (try? c.decodeIfPresent([Int].self, forKey: .refIds)) ?? []
        approved = (try? c.decodeIfPresent(Bool.self, forKey: .approved)) ?? false
    }
}

struct Chunk: Decodable, Hashable {
    var id: String
    var text: String
    var metadata: ChunkMetadata
}

/// A recommendation together with the guideline it belongs to. Chunk ids
/// repeat across guidelines (each has a "rec_1"), so identity needs both.
struct Recommendation: Identifiable, Hashable {
    let project: String
    let chunk: Chunk

    var id: String { project + "/" + chunk.id }

    static func == (a: Self, b: Self) -> Bool { a.id == b.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// A generated question/answer pair. `chunk_id` is top-level in current files
/// and under `metadata` in older ones, and uses the normalised id
/// ("esc-hf_2026_rec_1") rather than the chunk's own ("rec_1").
struct QAPair: Decodable, Hashable, Identifiable {
    var question: String
    var answer: String
    var chunkId: String?
    var lang: String?

    var id: String { (chunkId ?? "") + "|" + question }

    enum CodingKeys: String, CodingKey {
        case question, answer, lang, metadata
        case chunkId = "chunk_id"
    }

    private struct Meta: Decodable {
        var chunk_id: String?
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        question = try c.decodeIfPresent(String.self, forKey: .question) ?? ""
        answer = try c.decodeIfPresent(String.self, forKey: .answer) ?? ""
        lang = try c.decodeIfPresent(String.self, forKey: .lang)
        chunkId = try c.decodeIfPresent(String.self, forKey: .chunkId)
            ?? (try? c.decodeIfPresent(Meta.self, forKey: .metadata))??.chunk_id
    }

    func belongs(to chunkID: String) -> Bool {
        guard let chunkId else { return false }
        if chunkId == chunkID { return true }
        // "esc-hf_2026_rec_1" belongs to "rec_1" but not to "rec_11".
        return chunkId.hasSuffix("_" + chunkID)
    }
}
